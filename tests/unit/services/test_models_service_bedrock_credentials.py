"""Unit tests for `services.models_service.bedrock_credential_kwargs`.

Bedrock's access key and secret are passed as per-call litellm kwargs instead
of the process-wide AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, which
the AWS S3 connector reads as its credential fallback
(connectors/aws_s3/auth.py). Also pins the two embedding call sites
(search_service query-time, processors ingest-time) that must attach them.
"""

from types import SimpleNamespace

import pytest

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


class TestBedrockCredentialKwargs:
    def test_explicit_credentials_are_returned_as_per_call_kwargs(self, monkeypatch):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"),
        )

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "supersecret",
        }

    def test_iam_role_mode_passes_nothing(self, monkeypatch):
        """No explicit keys: leave litellm/boto3's default credential chain
        alone so IRSA / instance roles keep working."""
        monkeypatch.setattr("config.settings.get_openrag_config", lambda: _config())

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {}

    def test_partial_credentials_are_ignored(self, monkeypatch):
        """Half a credential pair is not usable - fall back to the chain."""
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE"),
        )

        assert bedrock_credential_kwargs("bedrock/cohere.embed-multilingual-v3") == {}

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

    Reuses the harness style of tests/unit/test_search_service_bedrock_embedding.py:
    the embed call happens before search_tool's auth check, so the call is
    captured and the function then short-circuits.
    """

    @staticmethod
    async def _run_search(monkeypatch, *, model_name, formatted_model):
        from services.search_service import SearchService

        calls = []

        async def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

        monkeypatch.setattr(
            "services.search_service.clients",
            SimpleNamespace(
                patched_embedding_client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
            ),
        )
        monkeypatch.setattr(
            "services.search_service.get_openrag_config",
            lambda: SimpleNamespace(providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=""))),
        )
        monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")

        class _FakeOpenSearchClient:
            async def search(self, index, body, params=None):
                return {
                    "aggregations": {
                        "embedding_models": {"buckets": [{"key": model_name, "doc_count": 3}]}
                    }
                }

        class _FakeSessionManager:
            def get_user_opensearch_client(self, user_id, jwt_token):
                return _FakeOpenSearchClient()

        class _FakeModelsService:
            async def get_litellm_model_name(self, name, strict=False):
                return formatted_model

        service = SearchService(
            session_manager=_FakeSessionManager(), models_service=_FakeModelsService()
        )
        await service.search_tool("what is the refund policy?", embedding_model=model_name)
        return calls

    @pytest.mark.asyncio
    async def test_query_embedding_passes_credentials(self, monkeypatch):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"),
        )

        calls = await self._run_search(
            monkeypatch,
            model_name="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert calls[0]["aws_access_key_id"] == "AKIAEXAMPLE"
        assert calls[0]["aws_secret_access_key"] == "supersecret"
        # The Cohere input_type contract must survive alongside them.
        assert calls[0]["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_query_embedding_omits_credentials_in_iam_role_mode(self, monkeypatch):
        monkeypatch.setattr("config.settings.get_openrag_config", lambda: _config())

        calls = await self._run_search(
            monkeypatch,
            model_name="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert "aws_access_key_id" not in calls[0]
        assert "aws_secret_access_key" not in calls[0]

    @pytest.mark.asyncio
    async def test_non_bedrock_query_embedding_gets_no_aws_kwargs(self, monkeypatch):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"),
        )

        calls = await self._run_search(
            monkeypatch,
            model_name="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
        )

        assert "aws_access_key_id" not in calls[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
