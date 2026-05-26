"""Unit tests for the bulk-delete helper used by the orphan-reconcile pass.

Pins the contract of `src/api/documents.py::delete_chunks_by_document_ids`:
- empty input is a no-op (no OpenSearch call)
- non-empty input enumerates visible chunk _ids and deletes them one-by-one
  by primary id (DLS-safe; `delete_by_query` is silently filtered under DLS)
- returns the count of successful single deletes
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.mark.asyncio
async def test_empty_ids_short_circuits_without_calling_opensearch():
    from api.documents import delete_chunks_by_document_ids

    opensearch_client = AsyncMock()
    deleted = await delete_chunks_by_document_ids([], opensearch_client, "test-index")

    assert deleted == 0
    opensearch_client.search.assert_not_awaited()
    opensearch_client.delete.assert_not_awaited()
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_deletes_each_visible_chunk_id_by_primary_id():
    """The helper must enumerate visible chunk _ids and issue a primary-id
    delete for each. delete_by_query is forbidden because DLS / certain
    security plugins silently no-op it (returns deleted:N but leaves docs)."""
    from api.documents import delete_chunks_by_document_ids

    opensearch_client = AsyncMock()
    # Visible chunk _ids for the requested document_ids.
    chunk_ids = ["chunk-1", "chunk-2", "chunk-3"]
    opensearch_client.search.return_value = {
        "_scroll_id": None,
        "hits": {"hits": [{"_id": cid} for cid in chunk_ids]},
    }
    opensearch_client.delete.return_value = {"result": "deleted"}

    deleted = await delete_chunks_by_document_ids(
        ["doc-a", "doc-b"], opensearch_client, "test-index"
    )

    assert deleted == len(chunk_ids)

    # delete_by_query must NOT be used — silently filtered under DLS.
    opensearch_client.delete_by_query.assert_not_awaited()

    # Search query must target the document_id field with terms(...).
    search_call = opensearch_client.search.await_args
    assert search_call.kwargs["index"] == "test-index"
    assert search_call.kwargs["body"]["query"] == {"terms": {"document_id": ["doc-a", "doc-b"]}}

    # One primary-id delete per visible chunk, refresh=True so the delete is
    # immediately visible to the re-index that typically follows.
    delete_calls = opensearch_client.delete.await_args_list
    assert len(delete_calls) == len(chunk_ids)
    for call, cid in zip(delete_calls, chunk_ids, strict=True):
        assert call.kwargs["index"] == "test-index"
        assert call.kwargs["id"] == cid
        assert call.kwargs.get("refresh") is True


@pytest.mark.asyncio
async def test_returns_zero_when_no_visible_chunks_match():
    """When the search returns no hits, no deletes are issued and the count
    is zero. This is the steady-state path (nothing to clean up)."""
    from api.documents import delete_chunks_by_document_ids

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {"_scroll_id": None, "hits": {"hits": []}}

    deleted = await delete_chunks_by_document_ids(["abc"], opensearch_client, "test-index")

    assert deleted == 0
    opensearch_client.delete.assert_not_awaited()
