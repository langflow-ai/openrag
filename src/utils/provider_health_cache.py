"""Short-TTL cache for ``GET /api/provider/health`` responses.

The provider-health banner mounts on every page and polls the endpoint every
5-30 seconds (per browser tab). With multiple tabs open, this fans out to many
identical watsonx.ai validation calls and significantly raises the chance of
hitting watsonx rate limits. A small in-process cache coalesces concurrent
identical health checks so a single watsonx round-trip serves all of them.

Only successful (200) responses on the default polled path are cached. The
explicit ``?provider=`` query bypass and the 503 error path are not cached, so
real outages and on-demand checks are never masked.
"""

import hashlib
import os

from cachetools import TTLCache

_DEFAULT_TTL_S = 10


def _ttl_seconds() -> int:
    raw = os.environ.get("OPENRAG_PROVIDER_HEALTH_TTL")
    if not raw:
        return _DEFAULT_TTL_S
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TTL_S
    return value if value > 0 else _DEFAULT_TTL_S


_HEALTH_CACHE: TTLCache[str, dict] = TTLCache(maxsize=64, ttl=_ttl_seconds())


def _fingerprint(value: str | None) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()[:16]


def cache_key(
    provider: str | None,
    embedding_provider: str | None,
    test_completion: bool,
    llm_model: str | None,
    embedding_model: str | None,
    endpoint: str | None,
    project_id: str | None,
    api_key: str | None,
    embedding_api_key: str | None = None,
    embedding_endpoint: str | None = None,
    embedding_project_id: str | None = None,
) -> str:
    """Build the cache key for a polled health-check call.

    The API keys are hashed (never stored in plaintext); rotating a key busts
    the cache automatically because the fingerprint changes.
    """
    parts = [
        provider or "",
        embedding_provider or "",
        "1" if test_completion else "0",
        llm_model or "",
        embedding_model or "",
        endpoint or "",
        project_id or "",
        _fingerprint(api_key),
        embedding_endpoint or "",
        embedding_project_id or "",
        _fingerprint(embedding_api_key),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def get(key: str) -> dict | None:
    return _HEALTH_CACHE.get(key)


def set_(key: str, value: dict) -> None:
    _HEALTH_CACHE[key] = value


def invalidate() -> None:
    """Clear the entire cache. Intended for settings-save flows and tests."""
    _HEALTH_CACHE.clear()
