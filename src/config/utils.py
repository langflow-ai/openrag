from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from cachetools import TTLCache
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from utils.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_K8S_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_ISSUER_PUBLIC_KEY_CACHE: TTLCache[str, Any] = TTLCache(maxsize=128, ttl=300)


# Read the K8S service account token
def _read_k8s_sa_token(k8s_sa_token_path: str) -> str | None:
    try:
        with open(k8s_sa_token_path) as f:
            return f.read().strip() or None
    except (FileNotFoundError, PermissionError):
        return None


def _strip_bearer_prefix(token: str) -> str:
    scheme, _, value = token.partition(" ")
    return value if scheme.lower() == "bearer" and value else token


def _issuer_allowed(
    issuer: str,
    allowed_issuers: set[str] | None,
    allowed_issuer_prefixes: tuple[str, ...],
) -> bool:
    if allowed_issuers and issuer in allowed_issuers:
        return True
    for prefix in allowed_issuer_prefixes:
        base = prefix.rstrip("/")
        if issuer == base or issuer.startswith(base + "/"):
            return True
    return False


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
    """Fetch and cache a JWT verification public key from a trusted issuer URL."""
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
    allowed_issuers: set[str] | None = None,
    allowed_issuer_prefixes: tuple[str, ...] = (),
    algorithms: tuple[str, ...] = ("ES256",),
    audience: str | list[str] | None = None,
    verify_tls: bool = True,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Verify a JWT by fetching the issuer public key after allowlist checks."""
    raw_token = _strip_bearer_prefix(token)
    try:
        header = jwt.get_unverified_header(raw_token)
        algorithm = header.get("alg")
        if algorithm not in algorithms:
            return None

        unverified_claims = jwt.decode(
            raw_token,
            options={"verify_signature": False, "verify_exp": False},
        )
        issuer = unverified_claims.get("iss")
        if not isinstance(issuer, str) or not _issuer_allowed(
            issuer,
            allowed_issuers,
            allowed_issuer_prefixes,
        ):
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
    except (ValueError, httpx.HTTPError, jwt.InvalidTokenError):
        return None


def get_opensearch_service_token(
    auth_server_url: str | None,
    tenant_id: str,
    k8s_sa_token_path: str = _DEFAULT_K8S_SA_TOKEN_PATH,
    *,
    verify_token: bool = True,
) -> str | None:
    """
    Fetch an OpenSearch service token from the internal auth server using the current K8S service account token.

    When ``verify_token`` is True (default), the returned JWT is verified
    against the auth server's public key (issuer pinned to ``auth_server_url``).

    Args:
        tenant_id (str): The tenant ID for which the token is requested.

    Returns:
        str | None: The raw OpenSearch token if successful, else None.
    """
    if not auth_server_url:
        return None

    token_endpoint = f"{auth_server_url.rstrip('/')}/internal/token/opensearch"
    try:
        k8s_token = _read_k8s_sa_token(k8s_sa_token_path)
        if not k8s_token:
            return None

        headers = {
            "Authorization": f"Bearer {k8s_token}",
            "Content-Type": "application/json",
        }
        json_body = {"tenant_id": tenant_id}

        # Verify is False for cluster-local/internal endpoints; see original curl -k
        with httpx.Client(verify=False, timeout=10) as client:
            resp = client.post(token_endpoint, headers=headers, json=json_body)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token")
    except Exception as exc:
        logger.warning(
            "Failed to fetch OpenSearch service token",
            error=str(exc),
            auth_server_url=auth_server_url,
        )
        return None

    if not token:
        return None

    if verify_token:
        claims = verify_jwt_from_issuer(
            token,
            allowed_issuer_prefixes=(auth_server_url.rstrip("/"),),
            verify_tls=False,
        )
        if claims is None:
            logger.warning(
                "OpenSearch service token failed JWT verification; rejecting",
                auth_server_url=auth_server_url,
            )
            return None

    return token
