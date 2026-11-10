import pytest

from services import search_cache
from utils.opensearch_delete import bulk_delete_document_ids


class _BulkClient:
    """Fake client; ``outcomes`` maps document id -> (result, status[, error])."""

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []

    async def bulk(self, *, body, refresh=False):
        self.calls.append({"body": body, "refresh": refresh})
        items = []
        for action in body:
            doc_id = action["delete"]["_id"]
            result, status, *error = self.outcomes.get(doc_id, ("deleted", 200))
            entry = {"_id": doc_id, "result": result, "status": status}
            if error:
                entry["error"] = error[0]
            items.append({"delete": entry})
        return {"errors": any(i["delete"]["status"] >= 400 for i in items), "items": items}


def _prime_caches():
    search_cache.SUGGEST_CACHE.set("g", {"files": ["old.pdf"]})


@pytest.mark.asyncio
async def test_batches_ids_and_refreshes_only_on_last_batch():
    client = _BulkClient()

    deleted = await bulk_delete_document_ids(
        client, index="documents", document_ids=[f"c{i}" for i in range(5)], batch_size=2
    )

    assert deleted == 5
    assert [len(c["body"]) for c in client.calls] == [2, 2, 1]
    assert [c["refresh"] for c in client.calls] == [False, False, True]
    assert client.calls[0]["body"][0] == {"delete": {"_index": "documents", "_id": "c0"}}


@pytest.mark.asyncio
async def test_exact_multiple_of_batch_size_refreshes_on_last_batch():
    client = _BulkClient()

    await bulk_delete_document_ids(
        client, index="documents", document_ids=["a", "b", "c", "d"], batch_size=2
    )

    assert [c["refresh"] for c in client.calls] == [False, True]


@pytest.mark.asyncio
async def test_refresh_false_never_refreshes():
    client = _BulkClient()

    await bulk_delete_document_ids(
        client, index="documents", document_ids=["a", "b", "c"], batch_size=2, refresh=False
    )

    assert [c["refresh"] for c in client.calls] == [False, False]


@pytest.mark.asyncio
async def test_empty_ids_make_no_request():
    client = _BulkClient()

    assert await bulk_delete_document_ids(client, index="documents", document_ids=[]) == 0
    assert client.calls == []


@pytest.mark.asyncio
async def test_missing_documents_are_ignored():
    client = _BulkClient({"a": ("not_found", 404)})

    deleted = await bulk_delete_document_ids(client, index="documents", document_ids=["a", "b"])

    assert deleted == 1


@pytest.mark.asyncio
async def test_item_failure_raises_after_all_batches_and_still_drops_caches():
    _prime_caches()
    client = _BulkClient({"a": ("error", 500, {"type": "boom"})})

    with pytest.raises(RuntimeError, match="boom"):
        await bulk_delete_document_ids(
            client, index="documents", document_ids=["a", "b", "c"], batch_size=1
        )

    assert len(client.calls) == 3
    assert search_cache.SUGGEST_CACHE.get("g") is None


@pytest.mark.asyncio
async def test_nothing_deleted_keeps_caches():
    _prime_caches()
    client = _BulkClient({"a": ("not_found", 404)})

    await bulk_delete_document_ids(client, index="documents", document_ids=["a"])

    assert search_cache.SUGGEST_CACHE.get("g") is not None
