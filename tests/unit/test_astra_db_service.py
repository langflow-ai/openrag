from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.astra_db_service import AstraDBService
from services.knowledge_access import KnowledgeAccessContext


class _FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self):
        return self.documents


class _FakeCollection:
    def __init__(self, *, documents=None, found_document=None, deleted_count=0):
        self.documents = documents or []
        self.found_document = found_document
        self.deleted_count = deleted_count
        self.find_calls = []
        self.find_one_calls = []
        self.delete_many_calls = []
        self.replace_one_calls = []

    def find(self, **kwargs):
        self.find_calls.append(kwargs)
        return _FakeCursor(self.documents)

    async def find_one(self, **kwargs):
        self.find_one_calls.append(kwargs)
        return self.found_document

    async def delete_many(self, **kwargs):
        self.delete_many_calls.append(kwargs)
        return SimpleNamespace(deleted_count=self.deleted_count)

    async def replace_one(self, *args, **kwargs):
        self.replace_one_calls.append((args, kwargs))
        return SimpleNamespace()


def _access_context() -> KnowledgeAccessContext:
    return KnowledgeAccessContext(
        user_id="u1",
        user_email="u1@example.com",
        groups=(),
        no_auth_mode=False,
    )


def test_astra_db_service_reads_optional_keyspace_from_env(monkeypatch):
    service = AstraDBService(collection_name="documents")
    monkeypatch.setenv("ASTRA_DB_APPLICATION_TOKEN", "token")
    monkeypatch.setenv("ASTRA_DB_API_ENDPOINT", "https://example.apps.astra.datastax.com")
    monkeypatch.setenv("ASTRA_DB_KEYSPACE", "rag_space")

    token, api_endpoint, keyspace = service._require_connection_settings()

    assert token == "token"
    assert api_endpoint == "https://example.apps.astra.datastax.com"
    assert keyspace == "rag_space"


@pytest.mark.asyncio
async def test_astra_db_service_has_indexed_documents_checks_for_existing_docs(monkeypatch):
    collection = _FakeCollection(found_document={"_id": "doc-1"})
    service = AstraDBService(collection_name="documents")

    monkeypatch.setattr(service, "_collection_exists", AsyncMock(return_value=True))

    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    exists = await service.has_indexed_documents()

    assert exists is True
    assert collection.find_one_calls[0]["projection"] == {"_id": True}


@pytest.mark.asyncio
async def test_astra_db_service_filename_exists_applies_access_filter(monkeypatch):
    collection = _FakeCollection(found_document={"_id": "doc-1"})
    service = AstraDBService(collection_name="documents")
    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    exists = await service.filename_exists("example.pdf", _access_context())

    assert exists is True
    assert collection.find_one_calls[0]["filter"] == {
        "$and": [
            {"metadata.filename": "example.pdf"},
            {
                "$or": [
                    {"metadata.owner": {"$exists": False}},
                    {"metadata.owner": {"$in": ["u1", "u1@example.com"]}},
                    {"metadata.allowed_users": {"$in": ["u1", "u1@example.com"]}},
                ]
            },
        ]
    }


@pytest.mark.asyncio
async def test_astra_db_service_delete_by_filename_returns_deleted_count(monkeypatch):
    collection = _FakeCollection(deleted_count=3)
    service = AstraDBService(collection_name="documents")
    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    deleted_count = await service.delete_by_filename("example.pdf", _access_context())

    assert deleted_count == 3
    assert collection.delete_many_calls[0]["filter"]["$and"][0] == {
        "metadata.filename": "example.pdf"
    }


@pytest.mark.asyncio
async def test_astra_db_service_search_returns_chunks_and_aggregations(monkeypatch):
    collection = _FakeCollection(
        documents=[
            {
                "_id": "doc-1",
                "content": "Purple elephants dance at night.",
                "$similarity": 0.91,
                "metadata": {
                    "filename": "animals.md",
                    "mimetype": "text/markdown",
                    "page": 1,
                    "owner": "u1",
                    "owner_name": "User One",
                    "owner_email": "u1@example.com",
                    "connector_type": "local",
                    "embedding_model": "text-embedding-3-small",
                    "allowed_users": ["u1@example.com"],
                    "allowed_groups": [],
                },
            },
            {
                "_id": "doc-2",
                "content": "Purple elephants prefer moonlight.",
                "$similarity": 0.84,
                "metadata": {
                    "filename": "animals.md",
                    "mimetype": "text/markdown",
                    "page": 2,
                    "owner": "u1",
                    "owner_name": "User One",
                    "owner_email": "u1@example.com",
                    "connector_type": "local",
                    "embedding_model": "text-embedding-3-small",
                    "allowed_users": ["u1@example.com"],
                    "allowed_groups": [],
                },
            },
        ]
    )
    service = AstraDBService(collection_name="documents")
    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    result = await service.search(
        query="purple elephants",
        embedding_model="text-embedding-3-small",
        filters={"data_sources": ["animals.md"]},
        limit=10,
        score_threshold=0.8,
        access_context=_access_context(),
        embed_query=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )

    assert [chunk["filename"] for chunk in result["results"]] == ["animals.md", "animals.md"]
    assert result["results"][0]["text"] == "Purple elephants dance at night."
    assert result["results"][0]["score"] == 0.91
    assert result["aggregations"]["data_sources"]["buckets"] == [
        {"key": "animals.md", "doc_count": 2}
    ]
    assert collection.find_calls[0]["sort"] == {"$vector": [0.1, 0.2, 0.3]}
    assert collection.find_calls[0]["include_similarity"] is True
    assert collection.find_calls[0]["filter"]["$and"][0] == {
        "metadata.filename": "animals.md"
    }


@pytest.mark.asyncio
async def test_astra_db_service_lists_connector_file_refs(monkeypatch):
    collection = _FakeCollection(
        documents=[
            {"metadata": {"document_id": "doc-1", "filename": "one.pdf"}},
            {"metadata": {"document_id": "doc-2", "filename": "two.pdf"}},
            {"metadata": {"document_id": "doc-1", "filename": "one.pdf"}},
        ]
    )
    service = AstraDBService(collection_name="documents")
    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    document_ids, filenames = await service.list_connector_file_refs(
        "google_drive",
        _access_context(),
    )

    assert document_ids == ["doc-1", "doc-2"]
    assert filenames == ["one.pdf", "two.pdf"]
    assert collection.find_calls[0]["filter"]["$and"][0] == {
        "metadata.connector_type": "google_drive"
    }


@pytest.mark.asyncio
async def test_astra_db_service_index_chunks_upserts_documents(monkeypatch):
    collection = _FakeCollection()
    service = AstraDBService(collection_name="documents")

    async def _get_collection(*args, **kwargs):
        return collection

    monkeypatch.setattr(service, "_get_collection", _get_collection)

    await service.index_chunks(
        [
            {
                "id": "doc-1_0",
                "text": "hello world",
                "embedding": [0.1, 0.2],
                "embedding_model": "text-embedding-3-small",
                "metadata": {
                    "document_id": "doc-1",
                    "filename": "hello.txt",
                    "connector_type": "local",
                },
            }
        ],
        _access_context(),
    )

    args, kwargs = collection.replace_one_calls[0]
    assert args[0] == {"_id": "doc-1_0"}
    assert args[1]["content"] == "hello world"
    assert args[1]["$vector"] == [0.1, 0.2]
    assert args[1]["metadata"]["document_id"] == "doc-1"
    assert kwargs["upsert"] is True
