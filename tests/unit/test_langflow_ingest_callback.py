import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.langflow_ingest import LangflowIngestBatch, LangflowIngestChunk, ingest_langflow_chunks
from services.document_index_writer import DocumentIndexContext
from services.langflow_file_service import LangflowFileService
from services.langflow_ingest_token_service import LangflowIngestTokenService

CALLBACK_GLOBAL_VARS = {
    "OPENRAG_INGEST_URL",
    "OPENRAG_INGEST_TOKEN",
    "OPENRAG_INGEST_RUN_ID",
    "OPENRAG_INGEST_BATCH_SIZE",
}

_OPENSEARCH_INGEST_COMPONENT = (
    "ext:openrag:OpenSearchVectorStoreComponentMultimodalMultiEmbedding@extra"
)


def _ingest_opensearch_component(flow: dict) -> dict:
    """Find the callback writer by stable component identity, never node ID."""
    matches = [
        node
        for node in flow["data"]["nodes"]
        if node.get("data", {}).get("type") == _OPENSEARCH_INGEST_COMPONENT
        and node.get("data", {}).get("node", {}).get("namespaced_id")
        == _OPENSEARCH_INGEST_COMPONENT
        and node.get("data", {}).get("node", {}).get("display_name")
        == "OpenSearch (Multi-Model Multi-Embedding)"
        and "VectorStore" in node.get("data", {}).get("node", {}).get("base_classes", [])
    ]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.asyncio
async def test_langflow_ingest_callback_indexes_authoritative_token_context():
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="doc-1",
        filename="source.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        owner="user-1",
        allowed_users=["user@example.com"],
        allowed_principals=["u:ms:tenant:user"],
        allowed_principal_labels=[
            {
                "principal": "u:ms:tenant:user",
                "kind": "user",
                "provider": "ms",
                "display_name": "User",
                "email": "user@example.com",
            }
        ],
        ingest_run_id="run-1",
    )
    token = token_service.create_token(context)

    class Writer:
        def __init__(self):
            self.calls = []

        async def index_chunks(self, context, chunks, *, final=False):
            self.calls.append((context, chunks, final))
            return {"indexed_chunks": len(chunks), "document_id": context.document_id}

    writer = Writer()
    body = LangflowIngestBatch(
        ingest_run_id="run-1",
        batch_id=1,
        final=True,
        chunks=[
            LangflowIngestChunk(
                id="doc-1_0",
                text="hello",
                vector=[0.1, 0.2],
                page=3,
                metadata={"owner": "forged-owner", "filename": "forged.pdf"},
            )
        ],
    )

    result = await ingest_langflow_chunks(
        body,
        authorization=f"Bearer {token}",
        x_openrag_ingest_token=None,
        token_service=token_service,
        writer=writer,
    )

    indexed_context, chunks, final = writer.calls[0]
    assert result["status"] == "ok"
    assert indexed_context.owner == "user-1"
    assert indexed_context.allowed_users == ["user@example.com"]
    assert indexed_context.allowed_principals == ["u:ms:tenant:user"]
    assert indexed_context.allowed_principal_labels == [
        {
            "principal": "u:ms:tenant:user",
            "kind": "user",
            "provider": "ms",
            "display_name": "User",
            "email": "user@example.com",
        }
    ]
    assert chunks[0].chunk_id == "doc-1_1_0"
    assert chunks[0].metadata["langflow_chunk_id"] == "doc-1_0"
    assert chunks[0].metadata["owner"] == "forged-owner"
    assert final is True

    with pytest.raises(HTTPException):
        await ingest_langflow_chunks(
            body,
            authorization=f"Bearer {token}",
            x_openrag_ingest_token=None,
            token_service=token_service,
            writer=writer,
        )


def test_ingest_token_round_trips_connector_file_id():
    """Bucket-connector chunks (COS/Azure/S3) rely on connector_file_id
    surviving the JWT round trip so post-ingest verification (which queries
    by connector_file_id) and dedupe/ACL sync can find them. Regression guard
    for the field being dropped by _context_to_payload/_payload_to_context."""
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="hashed-id",
        filename="report.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        owner="user-1",
        ingest_run_id="run-1",
        connector_file_id="my-bucket::報告書.pdf",
    )
    token = token_service.create_token(context)

    restored_context, _jti = token_service.validate_token(token)

    assert restored_context.connector_file_id == "my-bucket::報告書.pdf"


@pytest.mark.asyncio
async def test_failed_callback_cleanup_uses_signed_context_before_revocation():
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="same-content",
        filename="source.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        owner="user-a",
        index_name="documents",
        ingest_run_id="run-a",
    )
    token = token_service.create_token(context)
    token_service.revoke_token = MagicMock(wraps=token_service.revoke_token)
    writer = SimpleNamespace(delete_ingest_run=AsyncMock())
    service = LangflowFileService(
        ingest_token_service=token_service,
        document_index_writer=writer,
    )

    await service._cleanup_failed_callback_ingest(ingest_token=token, ingest_run_id="run-a")

    writer.delete_ingest_run.assert_awaited_once_with(
        "run-a",
        index_name="documents",
        document_id="same-content",
        owner="user-a",
        shared=False,
    )
    token_service.revoke_token.assert_called_once_with(token)


@pytest.mark.asyncio
async def test_failed_callback_cleanup_refuses_unscoped_delete_when_token_is_invalid():
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    token_service.revoke_token = MagicMock(wraps=token_service.revoke_token)
    writer = SimpleNamespace(delete_ingest_run=AsyncMock())
    service = LangflowFileService(
        ingest_token_service=token_service,
        document_index_writer=writer,
    )

    await service._cleanup_failed_callback_ingest(
        ingest_token="not-a-valid-token", ingest_run_id="run-a"
    )

    writer.delete_ingest_run.assert_not_awaited()
    token_service.revoke_token.assert_called_once_with("not-a-valid-token")


@pytest.mark.asyncio
async def test_langflow_ingest_callback_rewrites_langflow_chunk_ids():
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="doc-1",
        filename="source.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        ingest_run_id="run-1",
    )
    token = token_service.create_token(context)

    class Writer:
        def __init__(self):
            self.calls = []

        async def index_chunks(self, context, chunks, *, final=False):
            self.calls.append((context, chunks, final))
            return {"indexed_chunks": len(chunks)}

    writer = Writer()
    body = LangflowIngestBatch(
        ingest_run_id="run-1",
        batch_id=1,
        final=True,
        chunks=[
            LangflowIngestChunk(
                id="other-doc_0",
                text="hello",
                vector=[0.1, 0.2],
            )
        ],
    )

    await ingest_langflow_chunks(
        body,
        authorization=f"Bearer {token}",
        x_openrag_ingest_token=None,
        token_service=token_service,
        writer=writer,
    )

    _, chunks, _ = writer.calls[0]
    assert chunks[0].chunk_id == "doc-1_1_0"
    assert chunks[0].metadata["langflow_chunk_id"] == "other-doc_0"


@pytest.mark.asyncio
async def test_langflow_file_service_sends_backend_callback_global_vars(monkeypatch):
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    captured = {}

    class Response:
        status_code = 200
        reason_phrase = "OK"
        headers = {"content-type": "application/json"}
        text = '{"status":"ok"}'

        def json(self):
            return {"status": "ok"}

    async def langflow_request(method, endpoint, **kwargs):
        captured.update({"method": method, "endpoint": endpoint, **kwargs})
        return Response()

    async def add_provider_credentials_to_headers(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "services.langflow_file_service.clients",
        SimpleNamespace(langflow_request=langflow_request),
    )
    monkeypatch.setattr(
        "utils.langflow_headers.add_provider_credentials_to_headers",
        add_provider_credentials_to_headers,
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(embedding_model="text-embedding-3-small")
        ),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "unit-documents")

    service = LangflowFileService(ingest_token_service=token_service)
    result = await service.run_ingestion_flow(
        file_paths=["/tmp/source.pdf"],
        file_tuples=[("source.pdf", b"content", "application/pdf")],
        jwt_token="user-token",
        owner="user-1",
        owner_name="User One",
        owner_email="user@example.com",
        connector_type="local",
    )

    assert result == {"status": "ok"}
    payload = captured["json"]
    assert all(
        not key.startswith("OpenSearchVectorStoreComponentMultimodalMultiEmbedding-")
        for key in payload["tweaks"]
    )
    headers = captured["headers"]
    assert headers["X-Langflow-Global-Var-OPENRAG_INGEST_URL"].endswith("/internal/ingest/chunks")
    assert headers["X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN"]
    assert headers["X-Langflow-Global-Var-OPENRAG_INGEST_RUN_ID"]
    assert headers["X-Langflow-Global-Var-OPENRAG_INGEST_BATCH_SIZE"]

    decoded_context, _ = token_service.validate_token(
        headers["X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN"]
    )
    assert decoded_context.ingest_run_id == headers["X-Langflow-Global-Var-OPENRAG_INGEST_RUN_ID"]
    assert decoded_context.owner == "user-1"
    assert decoded_context.filename == "source.pdf"
    assert decoded_context.mimetype == "application/pdf"
    assert decoded_context.file_size == len(b"content")
    assert decoded_context.index_name == "unit-documents"
    assert decoded_context.is_sample_data is False
    assert headers["X-Langflow-Global-Var-DOCUMENT_ID"] == decoded_context.document_id


@pytest.mark.asyncio
async def test_langflow_file_service_marks_openrag_docs_callback_as_sample_data(monkeypatch):
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    captured = {}

    class Response:
        status_code = 200
        reason_phrase = "OK"
        headers = {"content-type": "application/json"}
        text = '{"status":"ok"}'

        def json(self):
            return {"status": "ok"}

    async def langflow_request(method, endpoint, **kwargs):
        captured.update({"method": method, "endpoint": endpoint, **kwargs})
        return Response()

    async def add_provider_credentials_to_headers(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "services.langflow_file_service.clients",
        SimpleNamespace(langflow_request=langflow_request),
    )
    monkeypatch.setattr(
        "utils.langflow_headers.add_provider_credentials_to_headers",
        add_provider_credentials_to_headers,
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(embedding_model="text-embedding-3-small")
        ),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "unit-documents")

    service = LangflowFileService(ingest_token_service=token_service)
    await service.run_ingestion_flow(
        file_paths=["/tmp/source.pdf"],
        file_tuples=[("source.pdf", b"content", "application/pdf")],
        jwt_token="user-token",
        connector_type="openrag_docs",
    )

    decoded_context, _ = token_service.validate_token(
        captured["headers"]["X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN"]
    )
    assert decoded_context.index_name == "unit-documents"
    assert decoded_context.is_sample_data is True


@pytest.mark.asyncio
async def test_default_documents_use_callback_sample_classification_without_node_tweak():
    from services.default_docs_service import _ingest_default_documents_langflow

    captured = {}

    class TaskService:
        async def create_langflow_upload_task(self, **kwargs):
            captured.update(kwargs)
            return "task-1"

    result = await _ingest_default_documents_langflow(
        langflow_file_service=SimpleNamespace(),
        session_manager=None,
        task_service=TaskService(),
        file_paths=["/tmp/example.md"],
        connector_type="openrag_docs",
    )

    assert result == "task-1"
    assert captured["connector_type"] == "openrag_docs"
    assert captured["tweaks"] is None


@pytest.mark.parametrize("flow_path", ["flows/ingestion_flow.json", "flows/openrag_url_mcp.json"])
def test_ingest_flows_resolve_callback_config_from_global_vars(flow_path):
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    node = _ingest_opensearch_component(flow)
    template = node["data"]["node"]["template"]

    assert template["openrag_ingest_url"]["value"] == "OPENRAG_INGEST_URL"
    assert template["openrag_ingest_token"]["value"] == "OPENRAG_INGEST_TOKEN"
    assert template["openrag_ingest_run_id"]["value"] == "OPENRAG_INGEST_RUN_ID"
    assert template["openrag_ingest_url"]["load_from_db"] is True
    assert template["openrag_ingest_token"]["load_from_db"] is True
    assert template["openrag_ingest_run_id"]["load_from_db"] is True
    assert template["openrag_ingest_url"]["input_types"] == ["Text", "Message"]
    assert template["openrag_ingest_token"]["input_types"] == ["Text", "Message"]
    assert template["openrag_ingest_run_id"]["input_types"] == ["Text", "Message"]
    assert template["openrag_ingest_token"]["_input_type"] == "SecretStrInput"
    assert "OPENRAG_INGEST_URL" in template["code"]["value"]
    assert "_openrag_ingest_global_placeholders" in template["code"]["value"]
    assert 'url = self._openrag_callback_value("openrag_ingest_url")' in template["code"]["value"]
    assert (
        'token = self._openrag_callback_value("openrag_ingest_token")' in template["code"]["value"]
    )
    assert (
        'ingest_run_id = self._openrag_callback_value("openrag_ingest_run_id")'
        in template["code"]["value"]
    )
    assert 'url = (self.openrag_ingest_url or "").strip()' not in template["code"]["value"]
    assert 'token = (self.openrag_ingest_token or "").strip()' not in template["code"]["value"]
    assert (
        'ingest_run_id = (self.openrag_ingest_run_id or "").strip()'
        not in template["code"]["value"]
    )
    assert "value.lower() in" not in template["code"]["value"]


@pytest.mark.parametrize("flow_path", ["flows/ingestion_flow.json", "flows/openrag_url_mcp.json"])
def test_ingest_flows_wire_callback_global_vars_into_opensearch(flow_path):
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    component = _ingest_opensearch_component(flow)
    template = component["data"]["node"]["template"]
    expected = {
        "openrag_ingest_url": "OPENRAG_INGEST_URL",
        "openrag_ingest_token": "OPENRAG_INGEST_TOKEN",
        "openrag_ingest_run_id": "OPENRAG_INGEST_RUN_ID",
    }

    for field_name, variable_name in expected.items():
        input_template = template[field_name]
        assert input_template["value"] == variable_name
        assert input_template["load_from_db"] is True
        assert input_template["show"] is True

    assert template["openrag_ingest_batch_size"]["value"] == 100
    assert template["openrag_ingest_batch_size"].get("load_from_db") is None
    assert template["openrag_ingest_batch_size"]["show"] is True


@pytest.mark.parametrize(
    "config_path",
    [
        "docker-compose.yml",
        "kubernetes/helm/openrag/values.yaml",
        "kubernetes/operator/internal/controller/env.go",
    ],
)
def test_langflow_callback_global_vars_are_allowlisted(config_path):
    config_text = Path(config_path).read_text(encoding="utf-8")

    assert (
        "LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT" in config_text
        or "variablesToGetFromEnvironment" in config_text
    )
    for variable_name in CALLBACK_GLOBAL_VARS:
        assert variable_name in config_text


@pytest.mark.parametrize(
    "config_path",
    [
        "docker-compose.yml",
        "kubernetes/helm/openrag/templates/langflow/langflow-dotenv.yaml",
        "kubernetes/operator/internal/controller/env.go",
    ],
)
def test_langflow_callback_global_vars_have_runtime_placeholders(config_path):
    config_text = Path(config_path).read_text(encoding="utf-8")

    for variable_name in CALLBACK_GLOBAL_VARS:
        assert f"{variable_name}=" in config_text or f'"{variable_name}":' in config_text


def test_ingest_token_prefers_jwt_signing_key_over_session_secret(monkeypatch):
    jwt_secret = "jwt-signing-secret-with-32-bytes!!"
    session_secret = "session-secret-should-not-be-used"

    monkeypatch.setattr("config.settings.JWT_SIGNING_KEY", jwt_secret)
    monkeypatch.setattr("config.settings.SESSION_SECRET", session_secret)

    token_service = LangflowIngestTokenService(ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="doc-jwt",
        filename="source.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        owner="user-1",
        ingest_run_id="run-jwt",
    )
    token = token_service.create_token(context)

    token_service.validate_token(token)

    session_service = LangflowIngestTokenService(secret=session_secret, ttl_seconds=60)
    with pytest.raises(ValueError, match="Invalid Langflow ingest token"):
        session_service.validate_token(token)
