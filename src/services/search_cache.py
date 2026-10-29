"""In-process caches for the search path.

Typing in the search box fires many near-identical requests, and every search
used to repeat the same expensive work: discovering the corpus' embedding
spaces (paginated aggregations) and embedding the query through the provider.
These caches make a repeated or retyped query cheap.

Three caches, each with different scoping rules:

* ``QUERY_EMBEDDING_CACHE`` - query vectors keyed by ``(route_model, text)``.
  A vector depends only on the text and the embedding route, never on the
  caller, so it is safe to share across users.
* ``SPACES_CACHE`` - embedding spaces present in the corpus. The OpenSearch
  client is per-user, so the key includes the user id and the filters.
* ``SUGGEST_CACHE`` - suggestion payloads containing file names and text
  snippets. Always keyed by user id so one user can never be served another
  user's results.

Every cache is single-flight: concurrent identical misses share one
computation instead of each paying for it.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, cast

from cachetools import TTLCache

QUERY_EMBEDDING_CACHE_SIZE = 512
QUERY_EMBEDDING_TTL_SECONDS = 3600
SPACES_CACHE_SIZE = 256
SPACES_TTL_SECONDS = 60
SUGGEST_CACHE_SIZE = 512
SUGGEST_TTL_SECONDS = 45


class SingleflightTTLCache:
    """TTL + size-bounded cache whose misses are computed once per key."""

    def __init__(self, maxsize: int, ttl: float) -> None:
        self._cache: TTLCache[Hashable, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._inflight: dict[Hashable, asyncio.Future[Any]] = {}
        # Bumped by clear() so a computation that began before a clear cannot
        # store its (now stale) result after it.
        self._generation = 0

    def get(self, key: Hashable) -> Any | None:
        return self._cache.get(key)

    def set(self, key: Hashable, value: Any) -> None:
        self._cache[key] = value

    def clear(self) -> None:
        self._generation += 1
        self._cache.clear()
        self._inflight.clear()

    def discard_where(self, predicate: Callable[[Hashable], bool]) -> None:
        """Drop matching entries and keep in-flight computations from storing."""
        self._generation += 1
        for key in [key for key in self._cache if predicate(key)]:
            del self._cache[key]
        for key in [key for key in self._inflight if predicate(key)]:
            del self._inflight[key]

    async def get_or_compute(
        self,
        key: Hashable,
        compute: Callable[[], Awaitable[Any]],
        *,
        cacheable: Callable[[Any], bool] = lambda _value: True,
    ) -> Any:
        """Return the cached value, or run ``compute`` once for all callers.

        ``cacheable`` lets the caller refuse to store degraded results (for
        example a response carrying provider warnings) so a transient failure
        is not pinned for the whole TTL. Exceptions are never cached.
        """
        while True:
            hit = self._cache.get(key)
            if hit is not None:
                return hit

            pending = self._inflight.get(key)
            if pending is None:
                break
            try:
                # shield: a cancelled waiter must not cancel the shared future.
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                # Only the leader's cancellation is recoverable; take over.
                if not pending.cancelled():
                    raise

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        generation = self._generation
        try:
            value = await compute()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            # Mark retrieved so asyncio does not warn when nobody was waiting.
            future.exception()
            raise
        else:
            if generation == self._generation and cacheable(value):
                self._cache[key] = value
            future.set_result(value)
            return value
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]


QUERY_EMBEDDING_CACHE = SingleflightTTLCache(
    QUERY_EMBEDDING_CACHE_SIZE, QUERY_EMBEDDING_TTL_SECONDS
)
SPACES_CACHE = SingleflightTTLCache(SPACES_CACHE_SIZE, SPACES_TTL_SECONDS)
SUGGEST_CACHE = SingleflightTTLCache(SUGGEST_CACHE_SIZE, SUGGEST_TTL_SECONDS)


def clear_search_caches() -> None:
    """Drop every cached entry (used by tests and after bulk index changes)."""
    QUERY_EMBEDDING_CACHE.clear()
    SPACES_CACHE.clear()
    SUGGEST_CACHE.clear()


def normalize_embedding_text(query: str) -> str:
    """Collapse whitespace only; case is preserved because it can change the vector."""
    return " ".join(query.split())


def normalize_query(query: str) -> str:
    """Canonical form used for result-cache keys (case and spacing insensitive)."""
    return " ".join(query.split()).lower()


def fingerprint(value: Any) -> str:
    """Stable, hashable representation of filter clauses / filter dicts."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def invalidate_user_suggestions(user_id: str) -> None:
    """Drop one user's cached suggestions (keys start with the user id)."""
    SUGGEST_CACHE.discard_where(
        lambda key: (
            isinstance(key, tuple) and len(key) > 0 and cast(tuple[Any, ...], key)[0] == user_id
        )
    )


def invalidate_user_spaces(user_id: str) -> None:
    """Drop one user's cached embedding spaces (keys start with the user id)."""
    SPACES_CACHE.discard_where(
        lambda key: (
            isinstance(key, tuple) and len(key) > 0 and cast(tuple[Any, ...], key)[0] == user_id
        )
    )


def invalidate_corpus_caches() -> None:
    """Drop results that depend on what is indexed.

    Query embeddings are kept: a vector depends only on the model and the
    text, and it is the one cache that saves a paid provider call.
    """
    SPACES_CACHE.clear()
    SUGGEST_CACHE.clear()
