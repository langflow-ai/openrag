"""JWT signature verification utilities for OAuth tokens."""

from __future__ import annotations

from typing import Any

import httpx
import jwt
from cachetools import TTLCache
from jwt.algorithms import RSAAlgorithm

from utils.logging_config import get_logger

logger = get_logger(__name__)

# JWKS cache: 1 hour TTL, max 10 entries
_jwks_cache: TTLCache = TTLCache(maxsize=10, ttl=3600)

# JWKS endpoints
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
MICROSOFT_JWKS_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"


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
        raise JWTVerificationError(
            "client_id is required for Google ID token verification"
        )

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


def verify_microsoft_access_token(
    token: str,
    client_id: str,
    tenant_id: str | None = None,
    allowed_tenant_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Verify Microsoft access token.

    Performs (all mandatory per RFC 7519 / RFC 8725):
    - Signature verification using Microsoft's JWKS
    - Algorithm enforcement (RS256)
    - Expiration validation
    - Audience validation (token must be issued for this client_id)
    - Issuer domain validation (token must come from a Microsoft authorization server)

    Optionally (business policy, not a standards requirement):
    - Tenant allow-list: when allowed_tenant_ids is provided, the verified tid claim
      must be in the set. Defaults to None (disabled) so multi-tenant deployments
      work without configuration.

    Args:
        token: Microsoft access token (JWT)
        client_id: Expected audience — OpenRAG's own Azure AD app client ID.
                   In a multi-tenant app this is always OpenRAG's client ID regardless
                   of which customer tenant the user belongs to.
        tenant_id: Hint for selecting the JWKS endpoint. Extracted from the token's
                   unverified `tid` claim if not provided. Only used to locate the
                   correct JWKS URL — never trusted for security decisions.
        allowed_tenant_ids: Optional set of permitted Azure AD tenant UUIDs.
                            When None, any tenant that passes cryptographic checks
                            is accepted. When provided, tokens from unlisted tenants
                            are rejected after signature verification.

    Returns:
        Verified token claims

    Raises:
        InvalidSignatureError: If signature is invalid
        ExpiredTokenError: If token has expired
        InvalidAudienceError: If audience doesn't match client_id
        InvalidIssuerError: If issuer is not a Microsoft authorization server,
                            or tenant is not in allowed_tenant_ids
        JWTVerificationError: For other verification failures
    """
    if not client_id:
        raise JWTVerificationError(
            "client_id is required for Microsoft access token verification"
        )

    try:
        # Extract tenant from the unverified token solely to pick the JWKS endpoint.
        # This value is NOT trusted for any security decision — we re-read tid from
        # the verified claims after signature check.
        if not tenant_id:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
            tenant_id = unverified_claims.get("tid")
            if not tenant_id:
                raise JWTVerificationError(
                    "Token is missing the 'tid' claim; cannot resolve JWKS endpoint. "
                    "Opaque (non-JWT) access tokens are not supported."
                )
            logger.debug(f"Extracted tenant_id from token: {tenant_id}")

        # Fetch JWKS for this tenant
        jwks_url = MICROSOFT_JWKS_URL_TEMPLATE.format(tenant=tenant_id)
        jwks = _fetch_jwks(jwks_url)

        # Get signing key
        signing_key = _get_signing_key(token, jwks)

        # Verify signature, expiry, and audience.
        # verify_iss is False because PyJWT only enforces it when issuer= is also
        # supplied; we perform issuer validation manually below against a domain
        # whitelist rather than a specific tenant URL.
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": False,
            },
        )

        # Issuer domain whitelist (RFC 8725 §3.6): confirm the token was issued by
        # a Microsoft authorization server. We check the domain prefix only — we do
        # NOT pin to a specific tenant UUID here, because in a multi-tenant app each
        # customer's tenant produces a different issuer URL but they all share the
        # same Microsoft authorization server infrastructure.
        issuer = claims.get("iss", "")
        _ms_issuer_prefixes = (
            "https://login.microsoftonline.com/",
            "https://sts.windows.net/",
        )
        if not any(issuer.startswith(p) for p in _ms_issuer_prefixes):
            raise InvalidIssuerError(
                f"Token issuer {issuer!r} is not a Microsoft authorization server"
            )

        # Tenant allow-list (optional business policy).
        # Only enforced when MICROSOFT_ALLOWED_TENANT_IDS is configured.
        # Uses the cryptographically verified tid from post-decode claims — cannot
        # be spoofed by a crafted token.
        verified_tid = claims.get("tid", "")
        if allowed_tenant_ids is not None and verified_tid not in allowed_tenant_ids:
            logger.warning(
                "Microsoft token tenant not in allow-list",
                verified_tid=verified_tid,
            )
            raise InvalidIssuerError(
                f"Tenant '{verified_tid}' is not in the configured allowed tenant list"
            )

        logger.debug("Microsoft access token verified successfully", tenant=verified_tid)
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
