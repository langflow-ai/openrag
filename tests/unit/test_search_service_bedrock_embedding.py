"""Unit tests for the query-time embedding call in SearchService.search_tool.

Proves the #1 landmine from the source issue: a Cohere-family embedding
model (Bedrock's cohere.embed-multilingual-v3) gets `input_type="search_query"`
passed through to the LLM gateway, while a non-Cohere model does not -
matching litellm's Bedrock/Cohere transformation contract (see architecture
notes: input_type is REQUIRED on every Bedrock Cohere embed call, with no
default).

Retrieval now routes through `services.llm_gateway.embeddings` (the same
credential-aware gateway Langflow uses) rather than a direct litellm/OpenAI-SDK
call - see `search_service.embed_with_space`. These tests mock that gateway
call directly and force the OpenSearch aggregation lookup to fail, which
exercises the code's own single-space fallback (built from the configured
embedding_model/embedding_provider) without needing to replicate the real
composite-aggregation response shape.

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


async def _run_search(monkeypatch, *, embedding_provider: str, embedding_model: str):
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint="")),
            knowledge=SimpleNamespace(embedding_provider=embedding_provider),
        ),
    )
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")

    calls = []

    async def fake_gateway_embeddings(body):
        calls.append(body)
        return {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", fake_gateway_embeddings)

    service = SearchService(session_manager=_FakeSessionManager(_FakeOpenSearchClient()))

    result = await service.search_tool("what is the refund policy?", embedding_model=embedding_model)

    # No auth context was set, so the function stops right after generating
    # embeddings - proof the embed call itself already happened above.
    assert result == {"results": [], "error": "Authentication required"}
    return calls


class TestCohereModelGetsInputType:
    @pytest.mark.asyncio
    async def test_bedrock_cohere_model_passes_search_query_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            embedding_provider="bedrock",
            embedding_model="cohere.embed-multilingual-v3",
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["model"] == "space:bedrock:cohere.embed-multilingual-v3"
        assert call["input"] == ["what is the refund policy?"]
        assert call["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_input_type_not_wrapped_in_extra_body(self, monkeypatch):
        """input_type must be a top-level key in the gateway request body,
        not nested under extra_body - the gateway forwards it straight to
        litellm.aembedding() as a kwarg (see llm_gateway.embeddings)."""
        calls = await _run_search(
            monkeypatch,
            embedding_provider="bedrock",
            embedding_model="cohere.embed-multilingual-v3",
        )

        assert "extra_body" not in calls[0]


class TestNonCohereModelOmitsInputType:
    @pytest.mark.asyncio
    async def test_openai_model_does_not_get_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]

    @pytest.mark.asyncio
    async def test_watsonx_model_does_not_get_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            embedding_provider="watsonx",
            embedding_model="ibm/slate-125m-english-rtrvr",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
