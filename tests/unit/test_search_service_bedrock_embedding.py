"""Unit tests for the query-time embedding call in SearchService.search_tool.

Proves the #1 landmine from the source issue: a Cohere-family embedding
model (Bedrock's cohere.embed-multilingual-v3) gets `input_type="search_query"`
passed as a plain kwarg to `.embeddings.create()`, while a non-Cohere model
does not - matching litellm's Bedrock/Cohere transformation contract (see
architecture notes: input_type is REQUIRED on every Bedrock Cohere embed
call, with no default).

The embedding call happens before SearchService.search_tool's auth check, so
these tests intentionally don't set an auth context - the call is captured,
then the function short-circuits with an "Authentication required" result
without needing to mock the rest of the OpenSearch hybrid-query pipeline.
"""

from types import SimpleNamespace

import pytest

from services.search_service import SearchService


class _RecordingEmbeddingClient:
    def __init__(self):
        self.calls = []

        async def create(**kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

        self.embeddings = SimpleNamespace(create=create)


class _FakeModelsService:
    def __init__(self, formatted_model: str):
        self.formatted_model = formatted_model

    async def get_litellm_model_name(self, model_name, strict=False):
        return self.formatted_model


class _FakeOpenSearchClient:
    def __init__(self, bucket_key: str):
        self.bucket_key = bucket_key

    async def search(self, index, body, params=None):
        return {
            "aggregations": {
                "embedding_models": {"buckets": [{"key": self.bucket_key, "doc_count": 3}]}
            }
        }


class _FakeSessionManager:
    def __init__(self, opensearch_client):
        self._client = opensearch_client

    def get_user_opensearch_client(self, user_id, jwt_token):
        return self._client


@pytest.fixture(autouse=True)
def _patch_config_env(monkeypatch):
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=""))),
    )
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")


async def _run_search(monkeypatch, *, model_name: str, formatted_model: str):
    embedding_client = _RecordingEmbeddingClient()
    monkeypatch.setattr(
        "services.search_service.clients",
        SimpleNamespace(patched_embedding_client=embedding_client),
    )

    service = SearchService(
        session_manager=_FakeSessionManager(_FakeOpenSearchClient(model_name)),
        models_service=_FakeModelsService(formatted_model),
    )

    result = await service.search_tool("what is the refund policy?", embedding_model=model_name)

    # No auth context was set, so the function stops right after generating
    # embeddings - proof the embed call itself already happened above.
    assert result == {"results": [], "error": "Authentication required"}
    return embedding_client.calls


class TestCohereModelGetsInputType:
    @pytest.mark.asyncio
    async def test_bedrock_cohere_model_passes_search_query_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            model_name="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["model"] == "bedrock/cohere.embed-multilingual-v3"
        assert call["input"] == ["what is the refund policy?"]
        assert call["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_input_type_not_wrapped_in_extra_body(self, monkeypatch):
        """The agentd patch forwards **kwargs straight to litellm.aembedding()
        for non-openai models - input_type must be a top-level kwarg, not
        nested under extra_body (that's only needed for the openai-SDK
        passthrough branch, not this one)."""
        calls = await _run_search(
            monkeypatch,
            model_name="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert "extra_body" not in calls[0]


class TestNonCohereModelOmitsInputType:
    @pytest.mark.asyncio
    async def test_openai_model_does_not_get_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            model_name="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]

    @pytest.mark.asyncio
    async def test_watsonx_model_does_not_get_input_type(self, monkeypatch):
        calls = await _run_search(
            monkeypatch,
            model_name="ibm/slate-125m-english-rtrvr",
            formatted_model="watsonx/ibm/slate-125m-english-rtrvr",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
