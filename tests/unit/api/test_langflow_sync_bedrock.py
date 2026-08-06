"""Unit tests for the Langflow flow-sync guard around non-Langflow embedding
providers (api.settings.langflow_sync / api.settings.helpers).

Bedrock has no Langflow embedding component - it is ingested and queried
entirely on the native path - so `FlowsService.change_langflow_model_value()`
raises ValueError for it. Feeding the selected embedding provider straight
into the flow sync therefore aborted the whole sync: silently (logged) in the
`update_settings` background task, and as a 500 during `onboarding`, which
re-raises. These tests pin the guard that skips the flow sync instead.
"""

from types import SimpleNamespace

import pytest

from api.settings.helpers import _is_langflow_embedding_provider
from api.settings.langflow_sync import _update_langflow_model_values
from services.flows_service import FlowsService


class _FakeFlowsService:
    """Stand-in that mirrors the real `change_langflow_model_value` contract:
    unknown providers raise ValueError before any flow work happens.

    `TestRealFlowsServiceContract` below keeps this faithful to the real one.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def change_langflow_model_value(self, provider, **kwargs):
        if provider not in ("watsonx", "ollama", "openai", "anthropic"):
            raise ValueError("provider must be 'watsonx', 'ollama', 'openai', or 'anthropic'")
        self.calls.append((provider, kwargs))
        return {"success": True, "results": []}


def _config(embedding_provider: str, embedding_model: str) -> SimpleNamespace:
    return SimpleNamespace(
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini"),
        knowledge=SimpleNamespace(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        ),
        providers=SimpleNamespace(
            openai=SimpleNamespace(configured=True),
            anthropic=SimpleNamespace(configured=False),
            watsonx=SimpleNamespace(configured=False),
            ollama=SimpleNamespace(configured=False),
        ),
    )


class TestRealFlowsServiceContract:
    @pytest.mark.asyncio
    async def test_change_langflow_model_value_rejects_bedrock(self):
        """The premise of the guard: the real service raises for bedrock."""
        with pytest.raises(ValueError):
            await FlowsService().change_langflow_model_value(
                "bedrock", embedding_model="cohere.embed-multilingual-v3"
            )


class TestIsLangflowEmbeddingProvider:
    @pytest.mark.parametrize("provider", ["openai", "watsonx", "ollama", "OpenAI"])
    def test_langflow_backed_providers(self, provider):
        assert _is_langflow_embedding_provider(provider) is True

    @pytest.mark.parametrize("provider", ["bedrock", "Bedrock", "", None])
    def test_non_langflow_providers(self, provider):
        assert _is_langflow_embedding_provider(provider) is False


class TestUpdateLangflowModelValuesSkipsBedrock:
    @pytest.mark.asyncio
    async def test_explicit_bedrock_embedding_provider_does_not_raise(self):
        """Onboarding passes body.embedding_provider straight through and
        re-raises on failure - this is the 500."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("openai", "text-embedding-3-small"),
            flows,
            embedding_model="cohere.embed-multilingual-v3",
            embedding_provider="bedrock",
        )

        assert flows.calls == []

    @pytest.mark.asyncio
    async def test_bedrock_from_config_fallback_does_not_raise(self):
        """`update_settings` only passes the model; the provider is resolved
        from the saved config, so the guard must look at the effective one."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("bedrock", "cohere.embed-multilingual-v3"),
            flows,
            embedding_model="cohere.embed-multilingual-v3",
        )

        assert flows.calls == []

    @pytest.mark.asyncio
    async def test_llm_sync_still_runs_when_embedding_provider_is_bedrock(self):
        """Skipping the embedding sync must not skip the LLM sync."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("bedrock", "cohere.embed-multilingual-v3"),
            flows,
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            embedding_provider="bedrock",
        )

        assert [provider for provider, _ in flows.calls] == ["openai"]
        assert flows.calls[0][1]["llm_model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_langflow_backed_embedding_provider_is_unaffected(self):
        """No regression for the providers that do have a flow component."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("openai", "text-embedding-3-small"),
            flows,
            embedding_model="text-embedding-3-large",
            embedding_provider="openai",
        )

        assert [provider for provider, _ in flows.calls] == ["openai"]
        assert flows.calls[0][1]["embedding_model"] == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_no_argument_reapply_never_reaches_bedrock(self):
        """`reapply_all_settings()` calls with no models/providers; the
        configured-provider sweep must stay on the Langflow-backed list."""
        flows = _FakeFlowsService()
        config = _config("bedrock", "cohere.embed-multilingual-v3")
        config.providers.bedrock = SimpleNamespace(configured=True)

        await _update_langflow_model_values(config, flows)

        assert "bedrock" not in [provider for provider, _ in flows.calls]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
