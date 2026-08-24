from typing import Any

import pytest

from services.document_index_writer import (
    DocumentIndexChunk,
    DocumentIndexContext,
    DocumentIndexWriter,
)
from utils.embedding_fields import get_embedding_field_name


class InMemoryIndices:
    async def exists(self, *, index: str) -> bool:
        return True

    async def get_mapping(self, *, index: str) -> dict[str, Any]:
        field = get_embedding_field_name("test-model")
        return {index: {"mappings": {"properties": {field: {"type": "knn_vector"}}}}}

    async def refresh(self, *, index: str) -> None:
        return None


class InMemoryOpenSearch:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.indices = InMemoryIndices()

    async def bulk(self, *, body: list[dict[str, Any]], refresh: bool | str) -> dict[str, Any]:
        for offset in range(0, len(body), 2):
            document_id = body[offset]["index"]["_id"]
            self.documents[document_id] = body[offset + 1]
        return {"errors": False}

    def visible_documents(self, owner: str) -> list[dict[str, Any]]:
        return [document for document in self.documents.values() if document.get("owner") == owner]


class CleanupOpenSearch(InMemoryOpenSearch):
    def __init__(self) -> None:
        super().__init__()
        self.cleanup_queries: list[dict[str, Any]] = []

    async def delete_by_query(self, *, index: str, body: dict, **_kwargs) -> dict[str, int]:
        self.cleanup_queries.append({"index": index, "body": body})
        return {"deleted": 0}


def make_context(owner: str | None) -> DocumentIndexContext:
    return DocumentIndexContext(
        document_id="same-content-hash",
        filename="report.pdf",
        mimetype="application/pdf",
        embedding_model="test-model",
        owner=owner,
    )


def make_chunk(text: str = "same file") -> DocumentIndexChunk:
    return DocumentIndexChunk(
        chunk_id="same-content-hash_0",
        text=text,
        vector=[0.1, 0.2, 0.3],
    )


@pytest.mark.asyncio
async def test_identical_chunks_remain_available_to_each_owner():
    opensearch = InMemoryOpenSearch()
    writer = DocumentIndexWriter(opensearch_client=opensearch)

    await writer.index_chunks(make_context("user-a"), [make_chunk()])
    await writer.index_chunks(make_context("user-b"), [make_chunk()])

    assert len(opensearch.documents) == 2
    assert len(opensearch.visible_documents("user-a")) == 1
    assert len(opensearch.visible_documents("user-b")) == 1


@pytest.mark.asyncio
async def test_reingesting_a_chunk_for_the_same_owner_updates_it_in_place():
    opensearch = InMemoryOpenSearch()
    writer = DocumentIndexWriter(opensearch_client=opensearch)

    await writer.index_chunks(make_context("user-a"), [make_chunk("old text")])
    await writer.index_chunks(make_context("user-a"), [make_chunk("new text")])

    assert len(opensearch.documents) == 1
    assert opensearch.visible_documents("user-a")[0]["text"] == "new text"


@pytest.mark.asyncio
async def test_reingesting_a_shared_chunk_updates_it_in_place():
    opensearch = InMemoryOpenSearch()
    writer = DocumentIndexWriter(opensearch_client=opensearch)

    await writer.index_chunks(make_context(None), [make_chunk("old shared text")])
    await writer.index_chunks(make_context(None), [make_chunk("new shared text")])

    assert len(opensearch.documents) == 1
    assert next(iter(opensearch.documents.values()))["text"] == "new shared text"


@pytest.mark.asyncio
async def test_failed_ingest_cleanup_scopes_same_document_id_to_its_owner():
    """Same bytes for A and B must never yield an unscoped admin delete."""
    opensearch = CleanupOpenSearch()
    writer = DocumentIndexWriter(opensearch_client=opensearch)

    await writer.delete_ingest_run(
        "run-a", index_name="documents", document_id="same-content", owner="user-a"
    )
    await writer.delete_ingest_run(
        "run-b", index_name="documents", document_id="same-content", owner="user-b"
    )

    owner_a_filters = opensearch.cleanup_queries[0]["body"]["query"]["bool"]["filter"]
    owner_b_filters = opensearch.cleanup_queries[1]["body"]["query"]["bool"]["filter"]
    assert {"term": {"owner": "user-a"}} in owner_a_filters
    assert {"term": {"owner": "user-b"}} in owner_b_filters
    assert {"term": {"document_id": "same-content"}} in owner_a_filters
    assert {"term": {"document_id": "same-content"}} in owner_b_filters


@pytest.mark.asyncio
async def test_failed_ingest_cleanup_scopes_shared_documents_to_ownerless_chunks():
    opensearch = CleanupOpenSearch()
    writer = DocumentIndexWriter(opensearch_client=opensearch)

    await writer.delete_ingest_run(
        "run-shared", index_name="documents", document_id="same-content", shared=True
    )

    filters = opensearch.cleanup_queries[0]["body"]["query"]["bool"]["filter"]
    assert {"bool": {"must_not": {"exists": {"field": "owner"}}}} in filters


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"owner": "user-a"},
        {"document_id": "same-content"},
        {"document_id": "same-content", "owner": "user-a", "shared": True},
    ],
)
async def test_failed_ingest_cleanup_refuses_unscoped_or_ambiguous_requests(kwargs):
    writer = DocumentIndexWriter(opensearch_client=CleanupOpenSearch())

    with pytest.raises(ValueError):
        await writer.delete_ingest_run("run-1", **kwargs)
