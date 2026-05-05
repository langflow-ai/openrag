import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import api.documents as documents_api
import connectors.aws_s3.api as s3_api
import connectors.ibm_cos.api as ibm_cos_api
import main
from connectors.service import ConnectorService
from models.processors import TaskProcessor
from session_manager import User


@pytest.mark.asyncio
async def test_ensure_index_exists_skips_non_opensearch_backend(monkeypatch):
    init_index = AsyncMock()

    monkeypatch.setattr("config.settings.get_knowledge_backend", lambda: "astra")
    monkeypatch.setattr(main, "init_index", init_index)

    await documents_api._ensure_index_exists("Bearer test-token")

    init_index.assert_not_called()


@pytest.mark.asyncio
async def test_process_document_standard_indexes_with_active_backend(monkeypatch, tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello world", encoding="utf-8")

    backend = Mock()
    backend.document_exists = AsyncMock(return_value=False)
    backend.index_chunks = AsyncMock()
    session_manager = Mock()

    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(knowledge=SimpleNamespace(embedding_model="")),
    )
    monkeypatch.setattr(
        "config.settings.clients.patched_embedding_client.embeddings.create",
        AsyncMock(
            return_value=SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )
        ),
    )

    processor = TaskProcessor(
        document_service=SimpleNamespace(session_manager=session_manager)
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="hash-1",
        owner_user_id="u1",
        original_filename="sample.txt",
        jwt_token="Bearer test-token",
        owner_name="User One",
        owner_email="u1@example.com",
        file_size=11,
        connector_type="local",
        embedding_model="text-embedding-3-small",
        extra_metadata={"source_url": "https://example.com/sample.txt"},
    )

    assert result == {"status": "indexed", "id": "hash-1"}
    exists_args = backend.document_exists.await_args.args
    assert exists_args[0] == "hash-1"
    assert exists_args[1].user_id == "u1"
    assert exists_args[1].user_email == "u1@example.com"

    index_args = backend.index_chunks.await_args.args
    indexed_chunks = index_args[0]
    access_context = index_args[1]
    assert access_context.user_id == "u1"
    assert indexed_chunks[0]["id"] == "hash-1_0"
    assert indexed_chunks[0]["embedding_model"] == "text-embedding-3-small"
    assert indexed_chunks[0]["metadata"]["document_id"] == "hash-1"
    assert indexed_chunks[0]["metadata"]["source_url"] == "https://example.com/sample.txt"
    assert not session_manager.get_user_opensearch_client.called


@pytest.mark.asyncio
async def test_connector_service_reingests_through_active_backend(monkeypatch):
    backend = Mock()
    backend.delete_by_document_id = AsyncMock(return_value=0)
    backend.delete_by_filename = AsyncMock(return_value=2)
    session_manager = Mock()
    captured_kwargs = {}

    async def _fake_process_document_standard(self, **kwargs):
        captured_kwargs.update(kwargs)
        return {"status": "indexed", "id": kwargs["file_hash"]}

    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )
    monkeypatch.setattr(
        "models.processors.TaskProcessor.process_document_standard",
        _fake_process_document_standard,
    )

    service = ConnectorService(
        patched_async_client=Mock(),
        embed_model="text-embedding-3-small",
        index_name="documents",
        session_manager=session_manager,
    )

    document = SimpleNamespace(
        id="bucket-a::reports/file.txt",
        filename="file.txt",
        mimetype="text/plain",
        content=b"hello world",
        source_url="s3://bucket-a/reports/file.txt",
        acl=None,
        created_time=datetime(2026, 4, 1, tzinfo=timezone.utc),
        modified_time=datetime(2026, 4, 2, tzinfo=timezone.utc),
        metadata={"etag": "123"},
    )

    result = await service.process_connector_document(
        document=document,
        owner_user_id="u1",
        connector_type="aws_s3",
        jwt_token="Bearer test-token",
        owner_name="User One",
        owner_email="u1@example.com",
    )

    assert result["status"] == "indexed"
    delete_args = backend.delete_by_document_id.await_args.args
    assert delete_args[0] == "bucket-a::reports/file.txt"
    assert delete_args[1].user_id == "u1"
    backend.delete_by_filename.assert_awaited_once_with(
        "file.txt",
        delete_args[1],
    )
    assert captured_kwargs["file_hash"] == "bucket-a::reports/file.txt"
    assert captured_kwargs["connector_type"] == "aws_s3"
    assert captured_kwargs["extra_metadata"]["source_url"] == "s3://bucket-a/reports/file.txt"
    assert captured_kwargs["extra_metadata"]["metadata"] == {"etag": "123"}
    assert not session_manager.get_user_opensearch_client.called


@pytest.mark.asyncio
async def test_s3_bucket_status_uses_active_backend(monkeypatch):
    backend = Mock()
    backend.list_connector_file_refs = AsyncMock(
        return_value=(
            ["bucket-a::one.txt", "bucket-a::two.txt", "bucket-b::three.txt"],
            [],
        )
    )
    resource = SimpleNamespace(
        buckets=SimpleNamespace(
            all=lambda: [
                SimpleNamespace(name="bucket-a"),
                SimpleNamespace(name="bucket-b"),
                SimpleNamespace(name="bucket-c"),
            ]
        )
    )
    connector_service = Mock()
    connector_service.connection_manager = Mock()
    connector_service.connection_manager.get_connection = AsyncMock(
        return_value=SimpleNamespace(user_id="u1", connector_type="aws_s3", config={})
    )
    session_manager = Mock()

    monkeypatch.setattr(s3_api, "create_s3_resource", lambda _config: resource)
    monkeypatch.setattr(
        s3_api,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    response = await s3_api.s3_bucket_status(
        connection_id="conn-1",
        connector_service=connector_service,
        session_manager=session_manager,
        user=User(user_id="u1", email="u1@example.com", name="User One", jwt_token="Bearer token"),
    )

    payload = json.loads(response.body)
    assert payload["buckets"] == [
        {"name": "bucket-a", "ingested_count": 2, "is_synced": True},
        {"name": "bucket-b", "ingested_count": 1, "is_synced": True},
        {"name": "bucket-c", "ingested_count": 0, "is_synced": False},
    ]
    assert not session_manager.get_user_opensearch_client.called


@pytest.mark.asyncio
async def test_ibm_cos_bucket_status_uses_active_backend(monkeypatch):
    backend = Mock()
    backend.list_connector_file_refs = AsyncMock(
        return_value=(
            ["alpha::one.txt", "beta::two.txt", "beta::three.txt"],
            [],
        )
    )
    resource = SimpleNamespace(
        buckets=SimpleNamespace(
            all=lambda: [
                SimpleNamespace(name="alpha"),
                SimpleNamespace(name="beta"),
                SimpleNamespace(name="gamma"),
            ]
        )
    )
    connector_service = Mock()
    connector_service.connection_manager = Mock()
    connector_service.connection_manager.get_connection = AsyncMock(
        return_value=SimpleNamespace(user_id="u1", connector_type="ibm_cos", config={})
    )
    session_manager = Mock()

    monkeypatch.setattr(ibm_cos_api, "create_ibm_cos_resource", lambda _config: resource)
    monkeypatch.setattr(
        ibm_cos_api,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    response = await ibm_cos_api.ibm_cos_bucket_status(
        connection_id="conn-1",
        connector_service=connector_service,
        session_manager=session_manager,
        user=User(user_id="u1", email="u1@example.com", name="User One", jwt_token="Bearer token"),
    )

    payload = json.loads(response.body)
    assert payload["buckets"] == [
        {"name": "alpha", "ingested_count": 1, "is_synced": True},
        {"name": "beta", "ingested_count": 2, "is_synced": True},
        {"name": "gamma", "ingested_count": 0, "is_synced": False},
    ]
    assert not session_manager.get_user_opensearch_client.called
