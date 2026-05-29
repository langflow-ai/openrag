import json
from pathlib import Path
from types import SimpleNamespace

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
    assert LangflowFileService.INGEST_OPENSEARCH_COMPONENT_ID not in payload["tweaks"]
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


@pytest.mark.parametrize(
    ("flow_path", "component_id"),
    [
        ("flows/ingestion_flow.json", LangflowFileService.INGEST_OPENSEARCH_COMPONENT_ID),
        ("flows/openrag_url_mcp.json", LangflowFileService.URL_INGEST_OPENSEARCH_COMPONENT_ID),
    ],
)
def test_ingest_flows_resolve_callback_config_from_global_vars(flow_path, component_id):
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    node = next(
        node
        for node in flow["data"]["nodes"]
        if node.get("id") == component_id
        and node.get("data", {}).get("node", {}).get("display_name")
        == "OpenSearch (Multi-Model Multi-Embedding)"
    )
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
    assert template["openrag_ingest_token"]["_input_type"] == "StrInput"
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


@pytest.mark.parametrize(
    ("flow_path", "component_id"),
    [
        ("flows/ingestion_flow.json", LangflowFileService.INGEST_OPENSEARCH_COMPONENT_ID),
        ("flows/openrag_url_mcp.json", LangflowFileService.URL_INGEST_OPENSEARCH_COMPONENT_ID),
    ],
)
def test_ingest_flows_wire_callback_global_vars_into_opensearch(flow_path, component_id):
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    nodes = {node.get("id"): node for node in flow["data"]["nodes"]}
    edges = flow["data"]["edges"]
    expected = {
        "openrag_ingest_url": "OPENRAG_INGEST_URL",
        "openrag_ingest_token": "OPENRAG_INGEST_TOKEN",
        "openrag_ingest_run_id": "OPENRAG_INGEST_RUN_ID",
    }

    for field_name, variable_name in expected.items():
        source_id = f"TextInput-OpenRAGIngest-{field_name.removeprefix('openrag_ingest_')}"
        text_node = nodes[source_id]
        input_template = text_node["data"]["node"]["template"]["input_value"]
        assert input_template["value"] == variable_name
        assert input_template["load_from_db"] is True

        assert any(
            edge.get("source") == source_id
            and edge.get("target") == component_id
            and edge.get("data", {}).get("targetHandle", {}).get("fieldName") == field_name
            for edge in edges
        )


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
