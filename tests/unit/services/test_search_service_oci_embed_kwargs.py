"""Query-time coverage for OCI Generative AI embedding calls.

Retrieval now routes query-time embeds through
`services.llm_gateway.embeddings` (the same credential-aware gateway
Langflow uses) rather than a direct litellm/OpenAI-SDK call - see
`search_service.embed_with_space`. These tests mock that gateway call
directly and force the OpenSearch aggregation lookup to fail, which
exercises the code's own single-space fallback (built from the configured
embedding_model/embedding_provider) without needing to replicate the real
composite-aggregation response shape.

`credential_values("oci")` (config.config_manager) resolves the static
api_key-style oci_* fields generically, but deliberately can't build an SDK
Signer for instance_principal/workload_identity auth - that construction
can fail (not running on OCI Compute, no Workload Identity) and belongs at
the call site. So `embed_with_space` builds it itself and forwards it
through the gateway's generic body passthrough (see
`services.llm_gateway.embeddings`).

The embedding call happens before SearchService.search_tool's auth check, so
these tests intentionally don't set an auth context - the call is captured,
then the function short-circuits with an "Authentication required" result
without needing to mock the rest of the OpenSearch hybrid-query pipeline.
"""

from types import SimpleNamespace

import pytest

from services.search_service import SearchService


class _FakeOpenSearchClient:
    """Always fails the embedding-space aggregation, forcing the code's own
    single-space fallback built from the configured embedding_model/provider -
    much simpler than replicating the real composite-aggregation JSON shape."""

    async def search(self, index, body, params=None):
        raise RuntimeError("no corpus indexed yet")


class _FakeSessionManager:
    def __init__(self, opensearch_client):
        self._client = opensearch_client

    def get_user_opensearch_client(self, user_id, jwt_token):
        return self._client


def _oci_config(*, auth_method="api_key"):
    return SimpleNamespace(
        user="ocid1.user.oc1..xxx",
        fingerprint="xx:xx:xx:xx",
        tenancy="ocid1.tenancy.oc1..xxx",
        compartment_id="ocid1.compartment.oc1..xxx",
        key="",
        key_file="/tmp/oci_key.pem",
        region="us-ashburn-1",
        configured=True,
        auth_method=auth_method,
    )


async def _run_search(
    monkeypatch,
    *,
    embedding_provider: str,
    embedding_model: str,
    oci_config=None,
    signer=None,
):
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=""), oci=oci_config),
            knowledge=SimpleNamespace(embedding_provider=embedding_provider),
        ),
    )
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.search_service.get_cached_oci_signer", lambda auth_method: signer)

    calls = []

    async def fake_gateway_embeddings(body):
        calls.append(body)
        return {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", fake_gateway_embeddings)

    service = SearchService(session_manager=_FakeSessionManager(_FakeOpenSearchClient()))

    result = await service.search_tool(
        "what is the capital of france?", embedding_model=embedding_model
    )

    # No auth context was set, so the function stops right after generating
    # embeddings - proof the embed call itself already happened above.
    assert result == {"results": [], "error": "Authentication required"}
    return calls


class TestOciApiKeyAuth:
    @pytest.mark.asyncio
    async def test_cohere_model_gets_input_type_and_oci_credentials(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            embedding_provider="oci",
            embedding_model="cohere.embed-multilingual-v3.0",
            oci_config=_oci_config(auth_method="api_key"),
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["model"] == "space:oci:cohere.embed-multilingual-v3.0"
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
        assert "oci_signer" not in call


class TestOciSignerAuth:
    @pytest.mark.asyncio
    async def test_instance_principal_forwards_signer_not_manual_credentials(self, monkeypatch):
        sentinel_signer = object()
        calls = await _run_search(
            monkeypatch,
            embedding_provider="oci",
            embedding_model="cohere.embed-multilingual-v3.0",
            oci_config=_oci_config(auth_method="instance_principal"),
            signer=sentinel_signer,
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["oci_signer"] is sentinel_signer
        assert call["oci_compartment_id"] == "ocid1.compartment.oc1..xxx"
        assert call["oci_region"] == "us-ashburn-1"
        # A signer supersedes the manual key-based fields entirely.
        assert "oci_user" not in call
        assert "oci_fingerprint" not in call
        assert "oci_tenancy" not in call
        assert "oci_key" not in call
        assert "oci_key_file" not in call


class TestNonOciModelOmitsOciKwargs:
    @pytest.mark.asyncio
    async def test_openai_model_gets_no_input_type_or_oci_kwargs(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["model"] == "space:openai:text-embedding-3-small"
        assert set(call.keys()) == {"model", "input"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
