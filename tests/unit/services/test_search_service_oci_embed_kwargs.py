"""Query-time coverage for OCI Generative AI embedding calls.

``SearchService.search_tool``'s inner ``embed_with_model`` closure calls
``clients.patched_embedding_client.embeddings.create(...)``. Once the model
resolves to a non-openai provider, agentd's ``patch_openai_with_mcp`` routes
that straight through to ``litellm.aembedding(**kwargs)`` -- so any kwargs
beyond ``model``/``input`` (input_type, the oci_* credential fields) must be
passed as plain kwargs on that call, not via ``extra_body`` or environment
variables. This test intercepts that call and asserts on exactly what was
sent for a query (as opposed to an ingest/document) embedding.

No auth context is set, so ``search_tool`` returns its "Authentication
required" error right after generating query embeddings -- which lets this
test exercise the embedding call without also needing to mock the
downstream KNN search response.
"""

from types import SimpleNamespace

import pytest

from services.search_service import SearchService


@pytest.mark.asyncio
async def test_embed_with_model_passes_cohere_input_type_and_oci_credentials(monkeypatch):
    captured_calls = []

    class FakeEmbeddings:
        async def create(self, model, input, **kwargs):
            captured_calls.append({"model": model, "input": input, **kwargs})
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    class FakeEmbeddingClient:
        embeddings = FakeEmbeddings()

    class FakeOpenSearchClient:
        async def search(self, **kwargs):
            # Aggregation query used to detect embedding models already in the corpus.
            return {
                "aggregations": {
                    "embedding_models": {
                        "buckets": [{"key": "cohere.embed-multilingual-v3.0", "doc_count": 3}]
                    }
                }
            }

    class FakeSessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            return FakeOpenSearchClient()

    class FakeModelsService:
        async def get_litellm_model_name(self, model_name, strict=False):
            assert model_name == "cohere.embed-multilingual-v3.0"
            assert strict is True
            return "oci/cohere.embed-multilingual-v3.0"

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
        providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=""), oci=oci_config),
    )

    monkeypatch.setattr("services.search_service.get_openrag_config", lambda: fake_openrag_config)
    monkeypatch.setattr(
        "services.search_service.clients",
        SimpleNamespace(patched_embedding_client=FakeEmbeddingClient()),
    )
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")

    service = SearchService(session_manager=FakeSessionManager(), models_service=FakeModelsService())

    result = await service.search_tool(
        "what is the capital of france?", embedding_model="cohere.embed-multilingual-v3.0"
    )

    assert result == {"results": [], "error": "Authentication required"}
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["model"] == "oci/cohere.embed-multilingual-v3.0"
    assert call["input"] == ["what is the capital of france?"]
    assert call["input_type"] == "search_query"
    assert call["oci_user"] == "ocid1.user.oc1..xxx"
    assert call["oci_fingerprint"] == "xx:xx:xx:xx"
    assert call["oci_tenancy"] == "ocid1.tenancy.oc1..xxx"
    assert call["oci_compartment_id"] == "ocid1.compartment.oc1..xxx"
    assert call["oci_key_file"] == "/tmp/oci_key.pem"
    assert call["oci_region"] == "us-ashburn-1"
    # Empty string ("key" not set) must not be forwarded as a kwarg.
    assert "oci_key" not in call


@pytest.mark.asyncio
async def test_embed_with_model_omits_extra_kwargs_for_non_cohere_openai_model(monkeypatch):
    """Sanity check: an OpenAI model gets no input_type/oci_* kwargs at all."""
    captured_calls = []

    class FakeEmbeddings:
        async def create(self, model, input, **kwargs):
            captured_calls.append({"model": model, "input": input, **kwargs})
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.4, 0.5, 0.6])])

    class FakeEmbeddingClient:
        embeddings = FakeEmbeddings()

    class FakeOpenSearchClient:
        async def search(self, **kwargs):
            return {
                "aggregations": {
                    "embedding_models": {
                        "buckets": [{"key": "text-embedding-3-small", "doc_count": 5}]
                    }
                }
            }

    class FakeSessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            return FakeOpenSearchClient()

    class FakeModelsService:
        async def get_litellm_model_name(self, model_name, strict=False):
            return model_name

    fake_openrag_config = SimpleNamespace(
        providers=SimpleNamespace(ollama=SimpleNamespace(endpoint="")),
    )

    monkeypatch.setattr("services.search_service.get_openrag_config", lambda: fake_openrag_config)
    monkeypatch.setattr(
        "services.search_service.clients",
        SimpleNamespace(patched_embedding_client=FakeEmbeddingClient()),
    )
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")

    service = SearchService(session_manager=FakeSessionManager(), models_service=FakeModelsService())

    result = await service.search_tool("hello", embedding_model="text-embedding-3-small")

    assert result == {"results": [], "error": "Authentication required"}
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["model"] == "text-embedding-3-small"
    assert call["input"] == ["hello"]
    assert set(call.keys()) == {"model", "input"}
