"""Ingest-path coverage for OCI Generative AI embedding calls.

Proves that ``TaskProcessor.process_document_standard`` (the non-Langflow
"standard processing pipeline" ingest path) passes:
  (a) the exact resolved LiteLLM model string ("oci/cohere.embed-...")
  (b) input_type="search_document" as a plain kwarg (Cohere-family models)
  (c) the oci_* credential kwargs built from config.providers.oci

to ``clients.patched_embedding_client.embeddings.create(...)``, since that
call is routed through litellm.aembedding() (via agentd's
patch_openai_with_mcp) rather than the OpenAI SDK once the model resolves to
a non-openai provider, and litellm's OCI integration reads every credential
field from call-time kwargs -- never from the environment.

Mirrors the existing ``tests/unit/test_processor_mapping_client.py`` harness
style (fake session manager / opensearch client / embedding client), but
narrows the fixture down to what's needed to exercise this one code path.
"""

from types import SimpleNamespace

import pytest

from models.processors import TaskProcessor
from services.document_index_writer import DocumentIndexWriter


@pytest.mark.asyncio
async def test_standard_processor_passes_cohere_input_type_and_oci_credentials(
    tmp_path,
    monkeypatch,
):
    captured_calls = []

    user_client = SimpleNamespace(search_calls=[])

    async def search(**kwargs):
        user_client.search_calls.append(kwargs)
        return {"_scroll_id": None, "hits": {"hits": []}}

    user_client.search = search

    admin_client = SimpleNamespace(bulk_calls=[])

    class Indices:
        async def exists(self, *, index):
            return True

        async def refresh(self, *, index):
            pass

    async def bulk(**kwargs):
        admin_client.bulk_calls.append(kwargs)
        return {"errors": False, "items": []}

    admin_client.indices = Indices()
    admin_client.bulk = bulk

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            return user_client

    class ModelsService:
        async def get_litellm_model_name(self, embedding_model):
            assert embedding_model == "cohere.embed-multilingual-v3.0"
            return "oci/cohere.embed-multilingual-v3.0"

    class EmbeddingClient:
        class Embeddings:
            async def create(self, model, input, **kwargs):
                captured_calls.append({"model": model, "input": input, **kwargs})
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    oci_config = SimpleNamespace(
        user="ocid1.user.oc1..xxx",
        fingerprint="xx:xx:xx:xx",
        tenancy="ocid1.tenancy.oc1..xxx",
        compartment_id="ocid1.compartment.oc1..xxx",
        key="",
        key_file="/tmp/oci_key.pem",
        region="us-ashburn-1",
        configured=True,
    )
    fake_openrag_config = SimpleNamespace(
        knowledge=SimpleNamespace(embedding_model=""),
        providers=SimpleNamespace(oci=oci_config),
    )

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
        "services.document_service.get_embedding_model",
        lambda: "cohere.embed-multilingual-v3.0",
    )
    monkeypatch.setattr("models.processors.get_openrag_config", lambda: fake_openrag_config)
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
        file_hash="file-oci-1",
        owner_user_id="user-1",
        original_filename="doc.md",
        jwt_token="Bearer user-token",
        embedding_model="cohere.embed-multilingual-v3.0",
    )

    assert result == {"status": "indexed", "id": "file-oci-1"}
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["model"] == "oci/cohere.embed-multilingual-v3.0"
    assert call["input"] == ["# Test\n\nhello world"]
    assert call["input_type"] == "search_document"
    assert call["oci_user"] == "ocid1.user.oc1..xxx"
    assert call["oci_fingerprint"] == "xx:xx:xx:xx"
    assert call["oci_tenancy"] == "ocid1.tenancy.oc1..xxx"
    assert call["oci_compartment_id"] == "ocid1.compartment.oc1..xxx"
    assert call["oci_key_file"] == "/tmp/oci_key.pem"
    assert call["oci_region"] == "us-ashburn-1"
    # Empty string ("key" not set) must not be forwarded as a kwarg.
    assert "oci_key" not in call
