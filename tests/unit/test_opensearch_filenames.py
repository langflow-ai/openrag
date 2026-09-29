"""Shared filename-existence executor (utils/opensearch_filenames).

All duplicate-detection altitudes (UI pre-check endpoint, connector duplicate
classifier, processor backstop) go through these two functions, so their
query semantics cannot drift apart.
"""

from unittest.mock import AsyncMock

import pytest

from utils.opensearch_filenames import (
    FILENAME_LOOKUP_BATCH_SIZE,
    filename_exists,
    find_existing_filenames,
)


def _agg_response(*filenames: str) -> dict:
    return {
        "aggregations": {"filenames": {"buckets": [{"key": f, "doc_count": 1} for f in filenames]}}
    }


@pytest.mark.asyncio
async def test_find_existing_filenames_uses_terms_aggregation():
    client = AsyncMock()
    client.search.return_value = _agg_response("a.pdf")

    result = await find_existing_filenames(["a.pdf", "b.pdf"], client, "docs")

    assert result == {"a.pdf"}
    body = client.search.await_args.kwargs["body"]
    # Aggregation, not hits: exact results regardless of per-file chunk counts.
    assert body["size"] == 0
    assert set(body["query"]["terms"]["filename"]) == {"a.pdf", "b.pdf"}
    assert "aggs" in body


@pytest.mark.asyncio
async def test_find_existing_filenames_dedupes_and_drops_empty():
    client = AsyncMock()
    client.search.return_value = _agg_response()

    await find_existing_filenames(["a.pdf", "a.pdf", "", None], client, "docs")

    assert client.search.await_args.kwargs["body"]["query"]["terms"]["filename"] == ["a.pdf"]


@pytest.mark.asyncio
async def test_find_existing_filenames_empty_input_short_circuits():
    client = AsyncMock()
    assert await find_existing_filenames([], client, "docs") == set()
    client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_filename_exists_expands_aliases():
    client = AsyncMock()
    client.search.return_value = _agg_response("report.md")

    assert await filename_exists("report.txt", client, "docs") is True
    queried = set(client.search.await_args.kwargs["body"]["query"]["terms"]["filename"])
    assert {"report.txt", "report.md"}.issubset(queried)


@pytest.mark.asyncio
async def test_filename_exists_false_when_no_alias_indexed():
    client = AsyncMock()
    client.search.return_value = _agg_response()
    assert await filename_exists("report.pdf", client, "docs") is False


@pytest.mark.asyncio
async def test_filename_exists_blank_input_short_circuits():
    client = AsyncMock()
    assert await filename_exists("", client, "docs") is False
    client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_existing_filenames_batches_large_candidate_sets():
    """A whole-container duplicate check can ask about more filenames than
    OpenSearch accepts in one terms query (index.max_terms_count, 65_536 by
    default), so candidates go out in batches and the results are unioned.
    """
    client = AsyncMock()
    candidates = [f"file-{i:05d}.pdf" for i in range(FILENAME_LOOKUP_BATCH_SIZE * 2 + 1)]

    async def search(*, index, body):
        asked = body["query"]["terms"]["filename"]
        assert len(asked) <= FILENAME_LOOKUP_BATCH_SIZE
        # One hit per batch, so the union has to come from every call.
        return _agg_response(asked[0])

    client.search = AsyncMock(side_effect=search)

    result = await find_existing_filenames(candidates, client, "docs")

    assert client.search.await_count == 3
    assert result == {"file-00000.pdf", "file-01024.pdf", "file-02048.pdf"}
