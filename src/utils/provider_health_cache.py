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

import asyncio
import hashlib
import json
from collections.abc import Mapping

from cachetools import TTLCache

from config.settings import PROVIDER_HEALTH_CACHE_TTL_SECONDS

# TTL is fixed at the value present in the environment when this module is first
# imported. Changing OPENRAG_PROVIDER_HEALTH_TTL requires a server restart.
_HEALTH_CACHE: TTLCache[str, dict] = TTLCache(maxsize=64, ttl=PROVIDER_HEALTH_CACHE_TTL_SECONDS)
# Per-key in-flight events for singleflight deduplication. Only the first
# coroutine to miss the cache for a given key calls the upstream provider;
# the rest await this event and read the result from the cache.
_in_flight: dict[str, asyncio.Event] = {}


def _fingerprint(value: str | None) -> str:
    return hashlib.blake2b((value or "").encode(), digest_size=8).hexdigest()  # nosec B324  # lgtm[py/weak-cryptographic-algorithm] — non-cryptographic cache key, not a security hash


def _fingerprint_mapping(values: Mapping[str, str] | None) -> str:
    """Fingerprint a provider's LiteLLM credential kwargs.

    Generic providers carry their secrets here rather than in the dedicated
    ``api_key``/``endpoint``/``project_id`` fields, so the key must cover them
    too — otherwise rotating a custom provider's credentials would keep
    serving the pre-rotation health verdict for the whole TTL. Sorted so dict
    ordering never changes the key.
    """
    if not values:
        return _fingerprint(None)
    return _fingerprint(json.dumps(dict(sorted(values.items())), separators=(",", ":")))


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
    credentials: Mapping[str, str] | None = None,
    embedding_credentials: Mapping[str, str] | None = None,
    embedding_oci_user: str | None = None,
    embedding_oci_fingerprint: str | None = None,
    embedding_oci_tenancy: str | None = None,
    embedding_oci_compartment_id: str | None = None,
    embedding_oci_key: str | None = None,
    embedding_oci_key_file: str | None = None,
    embedding_oci_auth_method: str | None = None,
) -> str:
    """Build the cache key for a polled health-check call.

    The API keys and credential kwargs are hashed (never stored in plaintext);
    rotating a key busts the cache automatically because the fingerprint
    changes. The OCI inline key is hashed the same way; the other OCI fields
    (identifiers, key file path) are not secrets and are included as-is,
    mirroring endpoint/project_id above.
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
        _fingerprint_mapping(credentials),
        _fingerprint_mapping(embedding_credentials),
        embedding_oci_user or "",
        embedding_oci_fingerprint or "",
        embedding_oci_tenancy or "",
        embedding_oci_compartment_id or "",
        _fingerprint(embedding_oci_key),
        embedding_oci_key_file or "",
        embedding_oci_auth_method or "",
    ]
    return hashlib.blake2b("|".join(parts).encode()).hexdigest()  # nosec B324  # lgtm[py/weak-cryptographic-algorithm] — non-cryptographic cache key, not a security hash


def get(key: str) -> dict | None:
    return _HEALTH_CACHE.get(key)


async def acquire(key: str) -> bool:
    """Attempt to become the computing leader for *key*.

    Returns True  → caller is the leader; it must call set_and_release() or
                    release_error() when validation completes or fails.
    Returns False → another coroutine was already computing this key; the
                    caller should call get() to read the result from cache.
    """
    if key in _in_flight:
        await _in_flight[key].wait()
        return False
    _in_flight[key] = asyncio.Event()
    return True


def _signal(key: str) -> None:
    event = _in_flight.pop(key, None)
    if event is not None:
        event.set()


def set_and_release(key: str, value: dict) -> None:
    """Write *value* to the cache and wake any coroutines waiting on *key*."""
    _HEALTH_CACHE[key] = value
    _signal(key)


def release_error(key: str) -> None:
    """Wake waiters for *key* without caching (validation failed)."""
    _signal(key)


def set_(key: str, value: dict) -> None:
    _HEALTH_CACHE[key] = value


def invalidate() -> None:
    """Clear the entire cache and any in-flight state. Intended for settings-save flows and tests."""
    _HEALTH_CACHE.clear()
    # Wake waiters before clearing so they don't hang; snapshot to avoid
    # mutation during iteration.
    for event in list(_in_flight.values()):
        event.set()
    _in_flight.clear()
