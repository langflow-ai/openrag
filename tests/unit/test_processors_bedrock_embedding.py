"""Unit tests for the ingest-time embedding call in TaskProcessor.process_document_standard.

Mirrors tests/unit/test_processor_mapping_client.py's mocking approach.
Proves a Cohere-family embedding model (Bedrock's cohere.embed-multilingual-v3)
gets `input_type="search_document"` passed as a plain kwarg to
`.embeddings.create()` during ingestion - the counterpart to
test_search_service_bedrock_embedding.py's query-time "search_query" case.
"""

from types import SimpleNamespace

import pytest

from models.processors import TaskProcessor
from services.document_index_writer import DocumentIndexWriter


class _FakeModelsService:
    def __init__(self, formatted_model: str):
        self.formatted_model = formatted_model

    async def get_litellm_model_name(self, embedding_model):
        return self.formatted_model


async def _run_ingest(monkeypatch, tmp_path, *, embedding_model: str, formatted_model: str):
    user_client = SimpleNamespace(search_calls=[])
    admin_client = SimpleNamespace(bulk_calls=[], refresh_calls=[])

    async def search(**kwargs):
        user_client.search_calls.append(kwargs)
        return {"_scroll_id": None, "hits": {"hits": []}}

    user_client.search = search

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
            return user_client

    embed_calls = []

    class EmbeddingClient:
        class Embeddings:
            async def create(self, model, input, **kwargs):
                embed_calls.append({"model": model, "input": input, **kwargs})
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    async def ensure_embedding_field_exists(client, model_name, index_name, dimensions):
        return f"chunk_embedding_{model_name}"

    monkeypatch.setattr(
        "config.settings.clients",
        SimpleNamespace(opensearch=admin_client, patched_embedding_client=EmbeddingClient()),
    )
    monkeypatch.setattr(
        "models.processors.clients",
        SimpleNamespace(opensearch=admin_client, patched_embedding_client=EmbeddingClient()),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    monkeypatch.setattr("models.processors.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.document_service.get_embedding_model", lambda: embedding_model
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
        models_service=_FakeModelsService(formatted_model),
        docling_service=None,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="file-1",
        owner_user_id="user-1",
        original_filename="doc.md",
        jwt_token="Bearer user-token",
        embedding_model=embedding_model,
    )

    assert result["status"] == "indexed"
    return embed_calls


class TestCohereModelGetsInputType:
    @pytest.mark.asyncio
    async def test_bedrock_cohere_model_passes_search_document_input_type(
        self, monkeypatch, tmp_path
    ):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert len(calls) == 1
        assert calls[0]["model"] == "bedrock/cohere.embed-multilingual-v3"
        assert calls[0]["input_type"] == "search_document"

    @pytest.mark.asyncio
    async def test_input_type_not_wrapped_in_extra_body(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert "extra_body" not in calls[0]


class TestNonCohereModelOmitsInputType:
    @pytest.mark.asyncio
    async def test_openai_model_does_not_get_input_type(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]


class TestQueryVsIngestInputTypeDiffer:
    @pytest.mark.asyncio
    async def test_ingest_uses_search_document_not_search_query(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert calls[0]["input_type"] == "search_document"
        assert calls[0]["input_type"] != "search_query"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
