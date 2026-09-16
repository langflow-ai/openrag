"""JWT signature verification utilities for OAuth tokens."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, cast

import httpx
import jwt
from cachetools import TTLCache
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

from utils.logging_config import get_logger

logger = get_logger(__name__)

# JWKS cache: 1 hour TTL, max 10 entries
_jwks_cache: TTLCache = TTLCache(maxsize=10, ttl=3600)

# JWKS endpoints
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# v2 tokens (iss = login.microsoftonline.com/…/v2.0) use /v2.0/keys.
# v1 tokens (iss = sts.windows.net/…)              use /keys (no /v2.0/).
# Selected at runtime based on the `ver` claim.
MICROSOFT_JWKS_URL_V2_TEMPLATE = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
MICROSOFT_JWKS_URL_V1_TEMPLATE = "https://login.microsoftonline.com/{tenant}/discovery/keys"
MICROSOFT_GRAPH_AUDIENCES = frozenset(
    {
        "00000003-0000-0000-c000-000000000000",
        "https://graph.microsoft.com",
    }
)


def _read_jwt_payload_without_trust(token: str) -> dict[str, Any]:
    """Read JWT payload JSON for metadata needed before signature verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTVerificationError("Token is not a compact JWT")

    payload_segment = parts[1]
    padding = "=" * (-len(payload_segment) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(f"{payload_segment}{padding}")
        payload = json.loads(payload_bytes)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise JWTVerificationError(f"Failed to read token payload: {e}") from e

    if not isinstance(payload, dict):
        raise JWTVerificationError("Token payload is not a JSON object")
    return payload


class JWTVerificationError(Exception):
    """Base exception for JWT verification errors."""

    pass


class InvalidSignatureError(JWTVerificationError):
    """JWT signature is invalid."""

    pass


class ExpiredTokenError(JWTVerificationError):
    """JWT token has expired."""

    pass


class InvalidAudienceError(JWTVerificationError):
    """JWT audience claim is invalid."""

    pass


class InvalidIssuerError(JWTVerificationError):
    """JWT issuer claim is invalid."""

    pass


def _fetch_jwks(url: str) -> dict[str, Any]:
    """
    Fetch JWKS from URL with caching.

    Args:
        url: JWKS endpoint URL

    Returns:
        JWKS dictionary

    Raises:
        JWTVerificationError: If JWKS fetch fails
    """
    # Check cache first
    if url in _jwks_cache:
        logger.debug(f"JWKS cache hit for {url}")
        return _jwks_cache[url]

    # Fetch from endpoint
    try:
        logger.debug(f"Fetching JWKS from {url}")
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        jwks = response.json()

        # Cache the result
        _jwks_cache[url] = jwks
        logger.debug(f"JWKS cached for {url}")

        return jwks
    except Exception as e:
        logger.error(f"Failed to fetch JWKS from {url}", error=str(e))
        raise JWTVerificationError(f"Failed to fetch JWKS: {e}") from e


def _get_signing_key(token: str, jwks: dict[str, Any]) -> Any:
    """
    Extract signing key from JWKS based on token header.

    Args:
        token: JWT token
        jwks: JWKS dictionary

    Returns:
        RSA public key object

    Raises:
        JWTVerificationError: If key not found
    """
    try:
        # Decode header without verification to get kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise JWTVerificationError("Token header missing 'kid' field")

        # Find matching key in JWKS
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                # Use PyJWT's built-in JWK to PEM conversion
                public_key = RSAAlgorithm.from_jwk(key)
                return public_key

        raise JWTVerificationError(f"Signing key with kid '{kid}' not found in JWKS")

    except jwt.DecodeError as e:
        raise JWTVerificationError(f"Failed to decode token header: {e}") from e


def verify_google_id_token(token: str, client_id: str) -> dict[str, Any]:
    """
    Verify Google ID token with FULL validation.

    Performs:
    - Signature verification using Google's JWKS
    - Issuer validation (accounts.google.com)
    - Expiration validation
    - Audience validation (requires client_id)

    Args:
        token: Google ID token (JWT)
        client_id: Expected audience (Google OAuth client ID)

    Returns:
        Verified token claims

    Raises:
        InvalidSignatureError: If signature is invalid
        ExpiredTokenError: If token has expired
        InvalidAudienceError: If audience doesn't match
        InvalidIssuerError: If issuer is invalid
        JWTVerificationError: For other verification failures
    """
    if not client_id:
        raise JWTVerificationError("client_id is required for Google ID token verification")

    try:
        # Fetch JWKS
        jwks = _fetch_jwks(GOOGLE_JWKS_URL)

        # Get signing key
        signing_key = _get_signing_key(token, jwks)

        # Verify token with FULL validation
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        logger.debug("Google ID token verified successfully")
        return claims

    except jwt.InvalidSignatureError as e:
        logger.warning("Google ID token has invalid signature", error=str(e))
        raise InvalidSignatureError(f"Invalid signature: {e}") from e
    except jwt.ExpiredSignatureError as e:
        logger.warning("Google ID token has expired", error=str(e))
        raise ExpiredTokenError(f"Token expired: {e}") from e
    except jwt.InvalidAudienceError as e:
        logger.warning("Google ID token has invalid audience", error=str(e))
        raise InvalidAudienceError(f"Invalid audience: {e}") from e
    except jwt.InvalidIssuerError as e:
        logger.warning("Google ID token has invalid issuer", error=str(e))
        raise InvalidIssuerError(f"Invalid issuer: {e}") from e
    except JWTVerificationError:
        raise
    except Exception as e:
        logger.error("Google ID token verification failed", error=str(e))
        raise JWTVerificationError(f"Verification failed: {e}") from e


def _resolve_ms_jwks_url(tenant_id: str, token_version: str) -> str:
    """
    Return the correct JWKS URL for the given tenant and token version.

    Per Microsoft docs: v1.0 tokens must be validated against the v1 metadata
    endpoint (no /v2.0/), v2.0 tokens against the v2 endpoint.
    """
    if token_version == "1.0":
        return MICROSOFT_JWKS_URL_V1_TEMPLATE.format(tenant=tenant_id)
    return MICROSOFT_JWKS_URL_V2_TEMPLATE.format(tenant=tenant_id)


# Known Microsoft issuer URL prefixes used when the JWKS key entry omits "issuer".
_MS_ISSUER_PREFIXES = (
    "https://login.microsoftonline.com/",
    "https://sts.windows.net/",
)


def _validate_ms_issuer(issuer: str, token_tid: str, signing_key_issuer: str | None) -> None:
    """
    Validate the token issuer following Microsoft's documented algorithm:

    1. When the JWKS key entry carries an ``issuer`` property, substitute
       ``{tenantid}`` and require an exact match against the token ``iss`` claim
       (Microsoft's documented multi-tenant issuer validation algorithm).
    2. When the key entry omits ``issuer`` (common for tenant-specific JWKS
       endpoints), fall back to verifying that ``iss`` starts with a known
       Microsoft issuer URL prefix — preventing cross-issuer attacks without
       rejecting otherwise valid tokens.
    3. In both cases, confirm that the ``tid`` claim matches the tenant segment
       embedded in the ``iss`` URL.

    Raises InvalidIssuerError on any failure.
    """
    if signing_key_issuer:
        # Keys from the tenant-independent endpoint carry "{tenantid}" as a
        # placeholder; tenant-specific keys may carry a literal issuer URL.
        resolved_key_issuer = signing_key_issuer.replace("{tenantid}", token_tid)
        if resolved_key_issuer != issuer:
            raise InvalidIssuerError(
                f"Token issuer {issuer!r} does not match signing key issuer "
                f"{resolved_key_issuer!r} (tid={token_tid!r})"
            )
    else:
        # JWKS key entry has no issuer field — validate against known MS prefixes.
        if not any(issuer.startswith(prefix) for prefix in _MS_ISSUER_PREFIXES):
            raise InvalidIssuerError(
                f"Token issuer {issuer!r} is not a recognised Microsoft issuer URL"
            )

    # Confirm the tid claim matches the tenant GUID segment in the iss URL.
    # Handles both v2 form (login.microsoftonline.com/{tid}/v2.0)
    # and v1 form (sts.windows.net/{tid}/).
    iss_segments = issuer.rstrip("/").split("/")
    tid_in_iss = next(
        (seg for seg in iss_segments if seg and "-" in seg and len(seg) == 36),
        None,
    )
    if tid_in_iss and tid_in_iss != token_tid:
        raise InvalidIssuerError(
            f"Tenant ID in issuer URL {tid_in_iss!r} does not match tid claim {token_tid!r}"
        )


def verify_microsoft_access_token(
    token: str,
    client_id: str,
    tenant_id: str | None = None,
    allowed_tenant_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Verify a Microsoft access token following the Microsoft identity platform docs.

    Scope of validation (per https://learn.microsoft.com/en-us/entra/identity-platform/
    access-token-claims-reference#validate-tokens):

    - OpenRAG accepts tokens whose aud is either our app client_id or an explicitly
      approved Microsoft Graph audience. Any other aud is rejected before claims are
      returned.

    Signature validation details (when performed):
    - JWKS endpoint selected by token version: v1 tokens (/discovery/keys),
      v2 tokens (/discovery/v2.0/keys).
    - Signing key looked up by kid header claim.
    - Issuer validated against the signing key's own issuer property in the JWKS
      document, with {tenantid} placeholder substituted by the token's tid claim
      (Microsoft's documented multi-tenant issuer validation algorithm).
    - tid segment of iss URL verified to match tid claim.

    Optionally (business policy, not a standards requirement):
    - Tenant allow-list enforced when MICROSOFT_ALLOWED_TENANT_IDS is configured.

    Args:
        token:              Raw JWT access token string.
        client_id:          OpenRAG's Azure AD app client ID.
        tenant_id:          Hint for JWKS endpoint selection; read from unsigned
                            payload metadata when not provided, then re-checked
                            after signature verification.
        allowed_tenant_ids: Optional set of permitted Azure AD tenant UUIDs.

    Returns:
        Verified token claims dict.

    Raises:
        InvalidSignatureError: Signature does not match the signing key.
        ExpiredTokenError:     Token exp claim is in the past.
        InvalidAudienceError:  aud matches our client_id but fails verification.
        InvalidIssuerError:    iss / tid mismatch, or tenant not in allow-list.
        JWTVerificationError:  Any other verification failure.
    """
    if not client_id:
        raise JWTVerificationError("client_id is required for Microsoft access token verification")

    try:
        # Read unsigned payload metadata only to choose the Microsoft JWKS endpoint.
        # Claims are returned only after signature and issuer verification below.
        untrusted_claims = _read_jwt_payload_without_trust(token)

        # Resolve tenant for JWKS URL (not trusted for security — re-checked post-sig).
        if not tenant_id:
            tenant_id = untrusted_claims.get("tid")
            if not tenant_id:
                raise JWTVerificationError(
                    "Token is missing the 'tid' claim; cannot resolve JWKS endpoint."
                )
            logger.debug(f"Extracted tenant_id from token: {tenant_id}")

        token_aud = untrusted_claims.get("aud", "")
        token_audiences = {str(aud) for aud in (token_aud if isinstance(token_aud, list) else [token_aud])}
        supported_audiences = {client_id, *MICROSOFT_GRAPH_AUDIENCES}
        if not token_audiences.intersection(supported_audiences):
            raise InvalidAudienceError(
                f"Unsupported Microsoft token audience: {sorted(token_audiences)!r}"
            )

        # ── Full validation for tokens issued directly to our application ──────────

        # Select JWKS endpoint based on token version (v1 vs v2).
        token_version = untrusted_claims.get("ver", "2.0")
        jwks_url = _resolve_ms_jwks_url(tenant_id, token_version)
        jwks = _fetch_jwks(jwks_url)

        # Find the signing key by kid and record its issuer property from the
        # JWKS document — needed for Microsoft's documented issuer validation.
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise JWTVerificationError("Token header missing 'kid' field")

        signing_key_entry = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if signing_key_entry is None:
            raise JWTVerificationError(f"Signing key with kid '{kid}' not found in JWKS")

        signing_key_issuer = signing_key_entry.get("issuer") or None
        # from_jwk() is typed as RSAPrivateKey | RSAPublicKey but JWKS endpoints
        # only ever contain public keys — cast so mypy accepts it for jwt.decode().
        signing_key = cast(RSAPublicKey, RSAAlgorithm.from_jwk(signing_key_entry))

        # Verify signature, expiry, and audience for every accepted Microsoft JWT.
        # verify_iss=False: issuer validated manually below per Microsoft's algorithm.
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=list(supported_audiences),
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": False,
            },
        )

        # Issuer validation per Microsoft docs:
        # Substitute tid into the signing key's issuer template and exact-match iss.
        verified_tid = claims.get("tid", "")
        issuer = claims.get("iss", "")
        _validate_ms_issuer(issuer, verified_tid, signing_key_issuer)

        # Tenant allow-list (optional business policy).
        if allowed_tenant_ids is not None and verified_tid not in allowed_tenant_ids:
            logger.warning(
                "Microsoft token tenant not in allow-list",
                verified_tid=verified_tid,
            )
            raise InvalidIssuerError(
                f"Tenant '{verified_tid}' is not in the configured allowed tenant list"
            )

        logger.debug(
            "Microsoft access token verified",
            tenant=verified_tid,
            token_version=token_version,
        )
        return claims

    except jwt.InvalidSignatureError as e:
        logger.warning("Microsoft access token has invalid signature", error=str(e))
        raise InvalidSignatureError(f"Invalid signature: {e}") from e
    except jwt.ExpiredSignatureError as e:
        logger.warning("Microsoft access token has expired", error=str(e))
        raise ExpiredTokenError(f"Token expired: {e}") from e
    except jwt.InvalidAudienceError as e:
        logger.warning("Microsoft access token has invalid audience", error=str(e))
        raise InvalidAudienceError(f"Invalid audience: {e}") from e
    except (jwt.InvalidIssuerError, InvalidIssuerError) as e:
        logger.warning("Microsoft access token has invalid issuer", error=str(e))
        raise InvalidIssuerError(f"Invalid issuer: {e}") from e
    except JWTVerificationError:
        raise
    except Exception as e:
        logger.error("Microsoft access token verification failed", error=str(e))
        raise JWTVerificationError(f"Verification failed: {e}") from e


def clear_jwks_cache():
    """Clear the JWKS cache. Useful for testing."""
    _jwks_cache.clear()
    logger.debug("JWKS cache cleared")


# Made with Bob
