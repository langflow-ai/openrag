from types import SimpleNamespace

import pytest

from models.processors import TaskProcessor
from services.document_index_writer import DocumentIndexWriter


@pytest.mark.asyncio
async def test_standard_processor_uses_shared_writer_for_embedding_mapping_and_writes(
    tmp_path,
    monkeypatch,
):
    user_client = SimpleNamespace(
        search_calls=[],
        index_calls=[],
    )
    admin_client = SimpleNamespace(bulk_calls=[], refresh_calls=[])
    mapping_clients = []

    async def search(**kwargs):
        user_client.search_calls.append(kwargs)
        return {"_scroll_id": None, "hits": {"hits": []}}

    async def index(**kwargs):
        user_client.index_calls.append(kwargs)

    user_client.search = search
    user_client.index = index

    class Indices:
        async def exists(self, *, index):
            return True

        async def refresh(self, *, index):
            admin_client.refresh_calls.append({"index": index})

    async def bulk(**kwargs):
        admin_client.bulk_calls.append(kwargs)
        return {"errors": False, "items": []}

    admin_client.indices = Indices()
    admin_client.bulk = bulk

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            assert user_id == "user-1"
            assert jwt_token == "Bearer user-token"
            return user_client

    class ModelsService:
        async def get_litellm_model_name(self, embedding_model):
            return embedding_model

    class EmbeddingClient:
        class Embeddings:
            async def create(self, model, input):
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    async def ensure_embedding_field_exists(client, model_name, index_name, dimensions):
        mapping_clients.append(client)
        assert model_name == "text-embedding-3-small"
        assert index_name == "documents"
        assert dimensions == 3
        return "chunk_embedding_text_embedding_3_small"

    monkeypatch.setattr(
        "config.settings.clients",
        SimpleNamespace(
            opensearch=admin_client,
            patched_embedding_client=EmbeddingClient(),
        ),
    )
    monkeypatch.setattr(
        "models.processors.clients",
        SimpleNamespace(
            opensearch=admin_client,
            patched_embedding_client=EmbeddingClient(),
        ),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    monkeypatch.setattr("models.processors.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.document_service.get_embedding_model",
        lambda: "text-embedding-3-small",
    )
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(knowledge=SimpleNamespace(embedding_model="")),
    )
    monkeypatch.setattr(
        "services.document_index_writer.ensure_embedding_field_exists",
        ensure_embedding_field_exists,
    )

    file_path = tmp_path / "doc.md"
    file_path.write_text("# Test\n\nhello world", encoding="utf-8")
    document_service = SimpleNamespace(
        session_manager=SessionManager(),
        document_index_writer=DocumentIndexWriter(opensearch_client=admin_client),
    )
    processor = TaskProcessor(
        document_service=document_service,
        models_service=ModelsService(),
        docling_service=None,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="file-1",
        owner_user_id="user-1",
        original_filename="doc.md",
        jwt_token="Bearer user-token",
        embedding_model="text-embedding-3-small",
    )

    assert result == {"status": "indexed", "id": "file-1"}
    assert mapping_clients == [admin_client]
    assert user_client.search_calls[0] == {
        "index": "documents",
        "body": {
            "size": 1,
            "_source": False,
            "query": {"term": {"document_id": "file-1"}},
        },
    }
    assert user_client.search_calls[1]["body"]["query"] == {"term": {"document_id": "file-1"}}
    assert user_client.index_calls == []
    assert admin_client.bulk_calls
    bulk_body = admin_client.bulk_calls[0]["body"]
    assert bulk_body[0] == {"index": {"_index": "documents", "_id": "file-1_0"}}
    assert bulk_body[1]["document_id"] == "file-1"
    assert bulk_body[1]["owner"] == "user-1"
    assert bulk_body[1]["chunk_embedding_text_embedding_3_small"] == [0.1, 0.2, 0.3]
