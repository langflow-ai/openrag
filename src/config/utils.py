from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from cachetools import TTLCache
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from utils.logging_config import get_logger

logger = get_logger(__name__)

_ISSUER_PUBLIC_KEY_CACHE: TTLCache[str, Any] = TTLCache(maxsize=128, ttl=300)


def _strip_bearer_prefix(token: str) -> str:
    scheme, _, value = token.partition(" ")
    return value if scheme.lower() == "bearer" and value else token


def _load_public_key_from_payload(payload: Any, key_id: str | None = None):
    if isinstance(payload, str):
        return load_pem_public_key(payload.encode("utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Public key response must be PEM text or JSON")

    public_key_pem = payload.get("public_key") or payload.get("pem") or payload.get("key")
    if public_key_pem:
        if isinstance(public_key_pem, bytes):
            return load_pem_public_key(public_key_pem)
        return load_pem_public_key(str(public_key_pem).encode("utf-8"))

    jwks = payload.get("keys")
    if isinstance(jwks, list) and jwks:
        jwk = next(
            (candidate for candidate in jwks if key_id and candidate.get("kid") == key_id),
            jwks[0],
        )
        return jwt.PyJWK.from_dict(jwk).key

    if payload.get("kty"):
        return jwt.PyJWK.from_dict(payload).key

    raise ValueError("Public key response does not contain a supported key format")


def get_public_key_from_issuer(
    issuer: str,
    key_id: str | None = None,
    *,
    verify_tls: bool = True,
    timeout: float = 10.0,
):
    """Fetch and cache a JWT verification public key (PEM / JWKS / JWK) from a
    JWT issuer URL. The issuer URL is expected to serve its own key material."""
    parsed = urlparse(issuer)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Issuer must be an absolute HTTP(S) URL")

    cache_key = f"{issuer}#{key_id or ''}"
    cached = _ISSUER_PUBLIC_KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with httpx.Client(verify=verify_tls, timeout=timeout) as client:
        response = client.get(issuer)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        key_payload = response.json()
    else:
        try:
            key_payload = response.json()
        except ValueError:
            key_payload = response.text

    public_key = _load_public_key_from_payload(key_payload, key_id)
    _ISSUER_PUBLIC_KEY_CACHE[cache_key] = public_key
    return public_key


def verify_jwt_from_issuer(
    token: str,
    *,
    algorithms: tuple[str, ...] = ("ES256",),
    audience: str | list[str] | None = None,
    verify_tls: bool = True,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Verify a JWT by discovering the signing key from the token's own ``iss``
    claim (JWKS/PEM served at the issuer URL), then checking the signature and
    the standard ``iss``/``sub``/``exp``/``iat`` claims.

    There is NO issuer allowlist: the ``iss`` URL is trusted to publish its own
    verification keys. This suits a deployment where an upstream gateway has
    already authenticated the caller and forwards the JWT — the gateway controls
    which ``iss`` reaches this code. If the header can be set by untrusted
    clients, pin the issuer instead.
    """
    raw_token = _strip_bearer_prefix(token)
    alg = kid = issuer = None
    try:
        header = jwt.get_unverified_header(raw_token)
        alg = header.get("alg")
        kid = header.get("kid")
        algorithm = alg
        if algorithm not in algorithms:
            logger.debug(
                "JWT rejected: unsupported alg",
                alg=alg,
                allowed=list(algorithms),
                kid=kid,
            )
            return None

        unverified_claims = jwt.decode(
            raw_token,
            options={"verify_signature": False, "verify_exp": False},
        )
        issuer = unverified_claims.get("iss")
        if not isinstance(issuer, str) or not issuer:
            logger.debug(
                "JWT rejected: missing or invalid iss claim",
                alg=alg,
                kid=kid,
            )
            return None

        public_key = get_public_key_from_issuer(
            issuer,
            header.get("kid"),
            verify_tls=verify_tls,
            timeout=timeout,
        )

        options: dict[str, Any] = {"require": ["iss", "sub", "exp", "iat"]}
        decode_kwargs: dict[str, Any] = {
            "algorithms": list(algorithms),
            "issuer": issuer,
            "options": options,
        }
        if audience is None:
            options["verify_aud"] = False
        else:
            decode_kwargs["audience"] = audience

        return jwt.decode(raw_token, public_key, **decode_kwargs)
    except (ValueError, httpx.HTTPError, jwt.InvalidTokenError) as e:
        logger.debug(
            "JWT verification failed",
            error=str(e),
            error_type=type(e).__name__,
            alg=alg,
            kid=kid,
            iss=issuer,
        )
        return None
