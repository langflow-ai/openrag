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
        raise JWTVerificationError(f"Failed to fetch JWKS: {e}")


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
        raise JWTVerificationError(f"Failed to decode token header: {e}")


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
        raise InvalidSignatureError(f"Invalid signature: {e}")
    except jwt.ExpiredSignatureError as e:
        logger.warning("Google ID token has expired", error=str(e))
        raise ExpiredTokenError(f"Token expired: {e}")
    except jwt.InvalidAudienceError as e:
        logger.warning("Google ID token has invalid audience", error=str(e))
        raise InvalidAudienceError(f"Invalid audience: {e}")
    except jwt.InvalidIssuerError as e:
        logger.warning("Google ID token has invalid issuer", error=str(e))
        raise InvalidIssuerError(f"Invalid issuer: {e}")
    except JWTVerificationError:
        raise
    except Exception as e:
        logger.error("Google ID token verification failed", error=str(e))
        raise JWTVerificationError(f"Verification failed: {e}")


def verify_microsoft_access_token(
    token: str, client_id: str, tenant_id: str | None = None
) -> dict[str, Any]:
    """
    Verify Microsoft access token with FULL validation.

    Performs:
    - Signature verification using Microsoft's JWKS
    - Issuer validation
    - Expiration validation
    - Audience validation (requires client_id)

    Args:
        token: Microsoft access token (JWT)
        client_id: Expected audience (Microsoft Graph OAuth client ID)
        tenant_id: Optional tenant ID for JWKS endpoint (extracted from token if not provided)

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
        raise JWTVerificationError("client_id is required for Microsoft access token verification")

    try:
        # Extract tenant from token if not provided
        if not tenant_id:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
            tenant_id = unverified_claims.get("tid", "common")
            logger.debug(f"Extracted tenant_id from token: {tenant_id}")

        # Fetch JWKS for this tenant
        jwks_url = MICROSOFT_JWKS_URL_TEMPLATE.format(tenant=tenant_id)
        jwks = _fetch_jwks(jwks_url)

        # Get signing key
        signing_key = _get_signing_key(token, jwks)

        # Verify token with FULL validation
        # Note: Microsoft tokens may have audience as client_id or resource URL
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        # Additional issuer validation for Microsoft
        issuer = claims.get("iss", "")
        expected_issuer_patterns = [
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        ]

        if not any(issuer.startswith(pattern) for pattern in expected_issuer_patterns):
            raise InvalidIssuerError(f"Unexpected issuer: {issuer}")

        logger.debug("Microsoft access token verified successfully")
        return claims

    except jwt.InvalidSignatureError as e:
        logger.warning("Microsoft access token has invalid signature", error=str(e))
        raise InvalidSignatureError(f"Invalid signature: {e}")
    except jwt.ExpiredSignatureError as e:
        logger.warning("Microsoft access token has expired", error=str(e))
        raise ExpiredTokenError(f"Token expired: {e}")
    except jwt.InvalidAudienceError as e:
        logger.warning("Microsoft access token has invalid audience", error=str(e))
        raise InvalidAudienceError(f"Invalid audience: {e}")
    except (jwt.InvalidIssuerError, InvalidIssuerError) as e:
        logger.warning("Microsoft access token has invalid issuer", error=str(e))
        raise InvalidIssuerError(f"Invalid issuer: {e}")
    except JWTVerificationError:
        raise
    except Exception as e:
        logger.error("Microsoft access token verification failed", error=str(e))
        raise JWTVerificationError(f"Verification failed: {e}")


def clear_jwks_cache():
    """Clear the JWKS cache. Useful for testing."""
    _jwks_cache.clear()
    logger.debug("JWKS cache cleared")


# Made with Bob
