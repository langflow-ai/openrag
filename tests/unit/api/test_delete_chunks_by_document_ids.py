"""Unit tests for the bulk-delete helper used by the orphan-reconcile pass.

Pins the contract of `src/api/documents.py::delete_chunks_by_document_ids`:
- empty input is a no-op (no OpenSearch call)
- non-empty input issues a single delete_by_query with terms(document_id, ...)
- returns the count reported by OpenSearch
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
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_issues_single_delete_by_query_with_terms_filter():
    from api.documents import delete_chunks_by_document_ids

    opensearch_client = AsyncMock()
    opensearch_client.delete_by_query.return_value = {"deleted": 12}

    ids = ["abc", "def", "ghi"]
    deleted = await delete_chunks_by_document_ids(ids, opensearch_client, "test-index")

    assert deleted == 12
    opensearch_client.delete_by_query.assert_awaited_once()
    call = opensearch_client.delete_by_query.await_args
    assert call.kwargs["index"] == "test-index"
    assert call.kwargs["body"] == {"query": {"terms": {"document_id": ids}}}
    # conflicts="proceed" so a concurrent reindex doesn't abort the bulk delete.
    assert call.kwargs.get("conflicts") == "proceed"


@pytest.mark.asyncio
async def test_returns_zero_when_response_missing_deleted_field():
    """Defensive: if OpenSearch returns an unexpected payload shape, we
    should not crash — we surface 0 deletions."""
    from api.documents import delete_chunks_by_document_ids

    opensearch_client = AsyncMock()
    opensearch_client.delete_by_query.return_value = {}  # no "deleted" key

    deleted = await delete_chunks_by_document_ids(["abc"], opensearch_client, "test-index")

    assert deleted == 0
