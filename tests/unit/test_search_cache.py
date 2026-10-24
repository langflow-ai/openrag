"""Unit tests for services/search_cache.py."""

import asyncio

import pytest

from services.search_cache import (
    SingleflightTTLCache,
    fingerprint,
    normalize_embedding_text,
    normalize_query,
)


@pytest.mark.asyncio
async def test_second_call_is_served_from_cache():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return "value"

    assert await cache.get_or_compute("k", compute) == "value"
    assert await cache.get_or_compute("k", compute) == "value"
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_misses_share_one_computation():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    calls = 0
    gate = asyncio.Event()

    async def compute():
        nonlocal calls
        calls += 1
        await gate.wait()
        return "value"

    tasks = [asyncio.create_task(cache.get_or_compute("k", compute)) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()

    assert await asyncio.gather(*tasks) == ["value"] * 5
    assert calls == 1


@pytest.mark.asyncio
async def test_exceptions_are_not_cached_and_reach_all_waiters():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    calls = 0
    gate = asyncio.Event()

    async def failing():
        nonlocal calls
        calls += 1
        await gate.wait()
        raise RuntimeError("boom")

    tasks = [asyncio.create_task(cache.get_or_compute("k", failing)) for _ in range(3)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, RuntimeError) for r in results)
    assert calls == 1

    async def working():
        return "ok"

    assert await cache.get_or_compute("k", working) == "ok"


@pytest.mark.asyncio
async def test_uncacheable_results_are_recomputed():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"warnings": ["degraded"]}

    def cacheable(value):
        return not value["warnings"]

    await cache.get_or_compute("k", compute, cacheable=cacheable)
    await cache.get_or_compute("k", compute, cacheable=cacheable)
    assert calls == 2


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_the_shared_computation():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    gate = asyncio.Event()

    async def compute():
        await gate.wait()
        return "value"

    owner = asyncio.create_task(cache.get_or_compute("k", compute))
    await asyncio.sleep(0)
    waiter = asyncio.create_task(cache.get_or_compute("k", compute))
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    gate.set()
    assert await owner == "value"


@pytest.mark.asyncio
async def test_cancelled_leader_does_not_cancel_waiters():
    cache = SingleflightTTLCache(maxsize=8, ttl=60)
    started = asyncio.Event()
    gate = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        started.set()
        await gate.wait()
        return "value"

    leader = asyncio.create_task(cache.get_or_compute("k", compute))
    await started.wait()
    waiters = [asyncio.create_task(cache.get_or_compute("k", compute)) for _ in range(2)]
    await asyncio.sleep(0)

    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader

    gate.set()
    assert await asyncio.gather(*waiters) == ["value", "value"]
    assert calls == 2
    assert cache.get("k") == "value"


@pytest.mark.asyncio
async def test_least_recently_used_entry_is_evicted_when_full():
    cache = SingleflightTTLCache(maxsize=2, ttl=60)

    async def make(value):
        return value

    for key in ("a", "b", "c"):
        await cache.get_or_compute(key, lambda key=key: make(key))

    assert cache.get("a") is None
    assert cache.get("b") == "b"
    assert cache.get("c") == "c"


def test_key_normalization():
    assert normalize_query("  Docling   Serve ") == "docling serve"
    # Embedding text keeps case: it can change the vector.
    assert normalize_embedding_text("  Docling   Serve ") == "Docling Serve"
    assert fingerprint({"b": [1], "a": [2]}) == fingerprint({"a": [2], "b": [1]})
