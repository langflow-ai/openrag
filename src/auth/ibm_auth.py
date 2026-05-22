"""IBM AMS JWT helper.

decode_ibm_jwt  — decode without signature verification (Traefik has already
                  validated the token before it reaches the backend).
validate_ibm_jwt — full RS256 validation for optional use when
                  IBM_JWT_PUBLIC_KEY_URL is configured.
fetch_ibm_public_key — fetch and cache IBM's public key PEM.
"""

import time

import httpx
import jwt
from cachetools import TTLCache
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from config import settings as app_settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Module-level cache; populated by fetch_ibm_public_key() if called.
_cached_public_key = None

# Short-lived cache for decoded IBM JWT claims. Traefik has already validated
# the signature; we cache to avoid repeated decode() calls for the same token.
# Each hit also rechecks token `exp` as defence-in-depth.
_IBM_JWT_CLAIMS_CACHE: TTLCache[str, dict] = TTLCache(
    maxsize=getattr(app_settings, "JWT_CLAIMS_CACHE_MAX_SIZE", 512),
    ttl=getattr(app_settings, "JWT_CLAIMS_CACHE_TTL_SECONDS", 60),
)


def decode_ibm_jwt(token: str) -> dict | None:
    """Decode *token* without signature verification, using an in-process cache.

    Used for the ibm-openrag-session cookie path where Traefik has already
    validated the JWT. Returns the claims dict, or None if decoding fails.
    """
    cached = _IBM_JWT_CLAIMS_CACHE.get(token)
    if cached is not None:
        if cached.get("exp", 0) > time.time():
            return cached
        _IBM_JWT_CLAIMS_CACHE.pop(token, None)  # evict immediately on stale hit

    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        _IBM_JWT_CLAIMS_CACHE[token] = claims
        return claims
    except jwt.InvalidTokenError as exc:
        logger.warning("IBM JWT decode failed", error=str(exc))
        return None


async def fetch_ibm_public_key(url: str):
    """Fetch IBM's JWT public key PEM from *url* and cache it."""
    global _cached_public_key
    logger.info("Fetching IBM JWT public key", url=url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        public_key_pem = data.get("public_key")
        if not public_key_pem:
            raise ValueError("IBM JWT public key not found in response")
        if isinstance(public_key_pem, str):
            public_key_pem = public_key_pem.encode("utf-8")
        _cached_public_key = load_pem_public_key(public_key_pem)
    logger.info("IBM JWT public key cached successfully")
    return _cached_public_key


def extract_ibm_credentials(basic_credentials: str) -> tuple[str, str]:
    """Decode a Basic credential string and return (username, password).

    Accepts either ``'Basic <base64>'`` or raw ``'<base64>'`` (no prefix).
    Returns ("unknown", "") if decoding fails.
    """
    import base64

    try:
        raw = basic_credentials[6:] if basic_credentials.startswith("Basic ") else basic_credentials
        decoded = base64.b64decode(raw).decode("utf-8")
        username, _, password = decoded.partition(":")
        return (username, password)
    except Exception:
        return ("unknown", "")


def validate_ibm_jwt(token: str, public_key) -> dict | None:
    """Validate *token* with *public_key* (full RS256 + expiry check).

    Returns the decoded claims dict on success, or None on any failure.
    """
    if public_key is None:
        logger.warning("IBM JWT validation skipped — no public key loaded")
        return None
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience="AMS-UI",
            issuer="IBMLH",
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("IBM JWT has expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("IBM JWT validation failed", error=str(exc))
        return None
