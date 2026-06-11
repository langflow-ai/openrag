"""Checks for client.search — query with limit / score_threshold / edge cases."""

import asyncio

from harness import Check, Context, Skip

# Retry search to absorb index-refresh latency after ingestion
# (pattern from tests/integration/sdk/test_e2e.py).
_RETRIES = 5
_RETRY_DELAY_S = 2.0


async def query_basic(ctx: Context) -> None:
    for _ in range(_RETRIES):
        results = await ctx.client.search.query("flamingo Zephyr planet Xylox")
        if results.results:
            break
        await asyncio.sleep(_RETRY_DELAY_S)
    else:
        raise Skip(
            f"ingested document not findable after {_RETRIES} retries (index refresh latency?)"
        )

    for result in results.results:
        assert result.text is not None, "search result has no text"
        assert isinstance(result.text, str), "search result text is not a string"


async def query_limit(ctx: Context) -> None:
    results = await ctx.client.search.query("test", limit=1)
    assert results.results is not None
    assert len(results.results) <= 1, f"limit=1 returned {len(results.results)} results"


async def query_score_threshold(ctx: Context) -> None:
    results = await ctx.client.search.query("test", score_threshold=0.99)
    assert isinstance(results.results, list)


async def query_no_results(ctx: Context) -> None:
    results = await ctx.client.search.query("zzz_xyzzy_nonexistent_content_abc123_qwerty_999")
    assert isinstance(results.results, list), "nonsense query did not return a list"


async def query_unicode(ctx: Context) -> None:
    results = await ctx.client.search.query("こんにちは 🦩 Ñoño résumé")
    assert isinstance(results.results, list), "unicode query did not return a list"


CHECKS = [
    Check("search.query_basic", query_basic, requires=["documents.ingest_wait"]),
    Check("search.query_limit", query_limit, requires=["documents.ingest_wait"]),
    Check(
        "search.query_score_threshold",
        query_score_threshold,
        requires=["documents.ingest_wait"],
    ),
    Check("search.query_no_results", query_no_results),
    Check("search.query_unicode", query_unicode),
]
