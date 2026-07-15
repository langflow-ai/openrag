"""check_filename_exists issues ONE bulk aliases query (shared semantics) and
retries it on transient failures."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
async def test_check_filename_exists_bulk_queries_all_aliases_and_retries():
    """All filename aliases go into a single terms-aggregation query; a
    transient failure retries the same bulk query."""
    processor = TaskProcessor()
    opensearch_client = AsyncMock()

    calls = []

    async def _search_side_effect(*, index, body):
        calls.append(body)
        if len(calls) == 1:
            raise asyncio.TimeoutError("transient timeout")
        return {"aggregations": {"filenames": {"buckets": []}}}

    opensearch_client.search.side_effect = _search_side_effect

    exists = await processor.check_filename_exists("report.txt", opensearch_client)

    assert exists is False
    assert len(calls) == 2  # first attempt timed out, retry succeeded
    for body in calls:
        queried = set(body["query"]["terms"]["filename"])
        # Both the .txt name and its .md ingestion alias are covered in one query.
        assert {"report.txt", "report.md"}.issubset(queried)


@pytest.mark.asyncio
async def test_check_filename_exists_true_when_any_alias_has_chunks():
    processor = TaskProcessor()
    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {
        "aggregations": {"filenames": {"buckets": [{"key": "report.md", "doc_count": 3}]}}
    }

    assert await processor.check_filename_exists("report.txt", opensearch_client) is True
    opensearch_client.search.assert_awaited_once()
