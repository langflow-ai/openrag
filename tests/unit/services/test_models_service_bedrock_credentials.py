"""Unit tests for `services.models_service.bedrock_credential_kwargs`.

Bedrock's access key and secret are passed as per-call litellm kwargs instead
of the process-wide AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, which
the AWS S3 connector reads as its credential fallback
(connectors/aws_s3/auth.py). Also pins the two embedding call sites
(search_service query-time, processors ingest-time) that must attach them.
"""

from types import SimpleNamespace

import pytest

from config.config_manager import (
    AnthropicConfig,
    BedrockConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from services.models_service import bedrock_credential_kwargs


def _config(*, access_key_id="", secret_access_key="", region="us-east-1") -> SimpleNamespace:
    return SimpleNamespace(
        providers=SimpleNamespace(
            bedrock=SimpleNamespace(
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        )
    )


def _openrag_config(
    *, embedding_provider: str, access_key_id="", secret_access_key="", region="us-east-1"
) -> SimpleNamespace:
    """A config whose `.providers` is a real ProvidersConfig - required for
    credential_values("bedrock") to actually run (the generic LLM gateway
    dispatches on `hasattr(providers, "credential_values")`, and only a real
    ProvidersConfig instance has that method)."""
    providers = ProvidersConfig(
        openai=OpenAIConfig(api_key="sk-test", configured=True),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        bedrock=BedrockConfig(
            region=region, access_key_id=access_key_id, secret_access_key=secret_access_key
        ),
    )
    return SimpleNamespace(
        providers=providers,
        knowledge=SimpleNamespace(embedding_provider=embedding_provider, embedding_model=""),
        agent=SimpleNamespace(llm_provider="openai", llm_model=""),
    )


class TestBedrockCredentialKwargs:
    def test_explicit_credentials_are_returned_as_per_call_kwargs(self, monkeypatch):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"),
        )

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "supersecret",
            "aws_region_name": "us-east-1",
        }

    def test_iam_role_mode_passes_region_but_not_credentials(self, monkeypatch):
        """No explicit keys: leave litellm/boto3's default credential chain
        alone so IRSA / instance roles keep working, but still forward the
        configured region - it's required in this mode too, and litellm
        shouldn't have to depend solely on the process-wide env var for it."""
        monkeypatch.setattr("config.settings.get_openrag_config", lambda: _config())

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {
            "aws_region_name": "us-east-1"
        }

    def test_no_region_and_no_credentials_passes_nothing(self, monkeypatch):
        monkeypatch.setattr("config.settings.get_openrag_config", lambda: _config(region=""))

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {}

    def test_partial_credentials_are_ignored(self, monkeypatch):
        """Half a credential pair is not usable - fall back to the chain -
        but the region is still forwarded."""
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE"),
        )

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {
            "aws_region_name": "us-east-1"
        }

    @pytest.mark.parametrize(
        "model",
        ["openai/text-embedding-3-small", "watsonx/ibm/slate-125m", "cohere.embed-v4:0", "", None],
    )
    def test_non_bedrock_models_get_nothing(self, model, monkeypatch):
        """Never attach AWS kwargs to a non-Bedrock call - litellm would
        reject the unknown parameter."""
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"),
        )

        assert bedrock_credential_kwargs(model) == {}

    def test_unreadable_config_does_not_raise(self, monkeypatch):
        def _boom():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr("config.settings.get_openrag_config", _boom)

        assert bedrock_credential_kwargs("bedrock/cohere.embed-v4:0") == {}


class TestEmbeddingCallSitesAttachCredentials:
    """The kwargs are worthless if the call sites don't pass them on.

    Retrieval now routes query-time embeds through
    `services.llm_gateway.embeddings` - the same credential-aware gateway
    Langflow uses - which resolves Bedrock's per-call AWS kwargs from
    `ProvidersConfig.credential_values("bedrock")` rather than
    `bedrock_credential_kwargs()` directly. These tests drive a real
    `SearchService.search_tool()` call end to end down to the actual
    `litellm.aembedding()` call, proving the credentials survive the whole
    path (search_tool -> gateway_embeddings -> resolve_call ->
    provider_credentials -> credential_values).
    """

    @staticmethod
    async def _run_search(monkeypatch, *, config, embedding_model):
        from services.search_service import SearchService

        calls = []

        async def fake_aembedding(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

        monkeypatch.setattr("litellm.aembedding", fake_aembedding)
        monkeypatch.setattr("services.search_service.get_openrag_config", lambda: config)
        monkeypatch.setattr("config.settings.get_openrag_config", lambda: config)
        monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")

        class _FakeOpenSearchClient:
            async def search(self, index, body, params=None):
                # Force the aggregation lookup to fail so the code falls
                # back to a single space built from the configured
                # embedding_model/embedding_provider - far simpler to drive
                # than the real composite-aggregation response shape.
                raise RuntimeError("no corpus indexed yet")

        class _FakeSessionManager:
            def get_user_opensearch_client(self, user_id, jwt_token):
                return _FakeOpenSearchClient()

        service = SearchService(session_manager=_FakeSessionManager())
        await service.search_tool("what is the refund policy?", embedding_model=embedding_model)
        return calls

    @pytest.mark.asyncio
    async def test_query_embedding_passes_credentials(self, monkeypatch):
        config = _openrag_config(
            embedding_provider="bedrock",
            access_key_id="AKIAEXAMPLE",
            secret_access_key="supersecret",
        )

        calls = await self._run_search(
            monkeypatch, config=config, embedding_model="cohere.embed-multilingual-v3"
        )

        assert calls[0]["model"] == "bedrock/cohere.embed-multilingual-v3"
        assert calls[0]["aws_access_key_id"] == "AKIAEXAMPLE"
        assert calls[0]["aws_secret_access_key"] == "supersecret"
        # The Cohere input_type contract must survive alongside them.
        assert calls[0]["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_query_embedding_omits_credentials_in_iam_role_mode(self, monkeypatch):
        config = _openrag_config(embedding_provider="bedrock")

        calls = await self._run_search(
            monkeypatch, config=config, embedding_model="cohere.embed-multilingual-v3"
        )

        assert "aws_access_key_id" not in calls[0]
        assert "aws_secret_access_key" not in calls[0]
        # Region is still required in IAM-role mode.
        assert calls[0]["aws_region_name"] == "us-east-1"

    @pytest.mark.asyncio
    async def test_non_bedrock_query_embedding_gets_no_aws_kwargs(self, monkeypatch):
        config = _openrag_config(
            embedding_provider="openai",
            access_key_id="AKIAEXAMPLE",
            secret_access_key="supersecret",
        )

        calls = await self._run_search(
            monkeypatch, config=config, embedding_model="text-embedding-3-small"
        )

        assert "aws_access_key_id" not in calls[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
