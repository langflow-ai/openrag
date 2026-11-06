"""Writes that change what is searchable must drop the corpus-dependent caches."""

import pytest

from services import search_cache
from services.document_index_writer import (
    DocumentIndexChunk,
    DocumentIndexContext,
    DocumentIndexWriter,
)
from utils.opensearch_delete import delete_document_ids


def _prime_caches() -> None:
    search_cache.SUGGEST_CACHE.set("g", {"files": ["old.pdf"]})
    search_cache.SPACES_CACHE.set("s", ["space"])
    search_cache.QUERY_EMBEDDING_CACHE.set("q", [0.1])


def _assert_corpus_caches_dropped() -> None:
    assert search_cache.SUGGEST_CACHE.get("g") is None
    assert search_cache.SPACES_CACHE.get("s") is None
    assert search_cache.QUERY_EMBEDDING_CACHE.get("q") == [0.1]


class _Indices:
    async def exists(self, *, index):
        return True

    async def get_mapping(self, *, index):
        return {}

    async def refresh(self, *, index):
        return None


class _WriteClient:
    def __init__(self, bulk_errors=False):
        self.indices = _Indices()
        self.bulk_errors = bulk_errors

    async def bulk(self, *, body, refresh):
        items = [
            {"index": {"_id": body[i]["index"]["_id"], "status": 500, "error": {"type": "boom"}}}
            if self.bulk_errors
            else {"index": {"_id": body[i]["index"]["_id"], "status": 200}}
            for i in range(0, len(body), 2)
        ]
        return {"errors": self.bulk_errors, "items": items}

    async def delete_by_query(self, **_kwargs):
        return {"deleted": 2}


def _writer(monkeypatch, client):
    writer = DocumentIndexWriter(opensearch_client=client)

    async def no_op_ensure(*_args, **_kwargs):
        return "embedding_field"

    monkeypatch.setattr(writer, "_ensure_index_and_embedding_field", no_op_ensure)
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    return writer


def _context():
    return DocumentIndexContext(
        document_id="doc",
        filename="report.pdf",
        mimetype="application/pdf",
        embedding_model="test-model",
        owner="user-a",
    )


_CHUNKS = [DocumentIndexChunk(chunk_id="doc_0", text="t", vector=[0.1, 0.2])]


@pytest.mark.asyncio
async def test_indexing_chunks_drops_corpus_caches(monkeypatch):
    writer = _writer(monkeypatch, _WriteClient())
    _prime_caches()

    await writer.index_chunks(_context(), _CHUNKS)

    _assert_corpus_caches_dropped()


@pytest.mark.asyncio
async def test_a_failed_batch_still_drops_corpus_caches(monkeypatch):
    writer = _writer(monkeypatch, _WriteClient(bulk_errors=True))
    monkeypatch.setattr("services.document_index_writer._BULK_RETRY_DELAY_SECONDS", 0)
    _prime_caches()

    with pytest.raises(Exception):  # noqa: B017 - any bulk failure type
        await writer.index_chunks(_context(), _CHUNKS)

    _assert_corpus_caches_dropped()


@pytest.mark.asyncio
async def test_deleting_an_ingest_run_drops_corpus_caches(monkeypatch):
    writer = _writer(monkeypatch, _WriteClient())
    _prime_caches()

    await writer.delete_ingest_run("run-1")

    _assert_corpus_caches_dropped()


class _DeleteClient:
    def __init__(self, results):
        self.results = results

    async def delete(self, *, index, id, refresh):
        result = self.results[id]
        if isinstance(result, Exception):
            raise result
        return {"result": result}


@pytest.mark.asyncio
async def test_deleting_documents_drops_corpus_caches():
    _prime_caches()

    deleted = await delete_document_ids(
        _DeleteClient({"a": "deleted"}), index="documents", document_ids=["a"]
    )

    assert deleted == 1
    _assert_corpus_caches_dropped()


@pytest.mark.asyncio
async def test_a_delete_that_removed_nothing_keeps_the_caches():
    _prime_caches()

    await delete_document_ids(
        _DeleteClient({"a": "not_found"}), index="documents", document_ids=["a"]
    )

    assert search_cache.SUGGEST_CACHE.get("g") is not None


@pytest.mark.asyncio
async def test_a_delete_that_fails_midway_still_drops_caches():
    _prime_caches()

    with pytest.raises(RuntimeError):
        await delete_document_ids(
            _DeleteClient({"a": "deleted", "b": RuntimeError("down")}),
            index="documents",
            document_ids=["a", "b"],
        )

    _assert_corpus_caches_dropped()
