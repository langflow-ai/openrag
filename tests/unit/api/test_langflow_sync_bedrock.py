"""Unit tests for Bedrock's Langflow flow sync (api.settings.langflow_sync).

Bedrock has no dedicated Langflow embedding component, but
`FlowsService.change_langflow_model_value()` proxies every provider through
the same OpenRAG-internal OpenAI-compatible endpoint (see
`flows_service.py`'s `proxy_fields`), so bedrock is synced exactly like
openai/watsonx/ollama - no special-casing needed. These tests pin that: the
sync reaches `change_langflow_model_value("bedrock", ...)` on every code
path, the same way it does for the Langflow-native providers.
"""

from types import SimpleNamespace

import pytest

from api.settings import langflow_sync
from api.settings.langflow_sync import _update_langflow_model_values


@pytest.fixture(autouse=True)
def _stub_langflow_global_variable_push(monkeypatch):
    """These tests pin flows_service.change_langflow_model_value() calls
    only - the SELECTED_EMBEDDING_* global variable push is a real Langflow
    API call, out of scope here (see test_langflow_global_variables.py)."""

    async def _noop(name, value):
        return None

    monkeypatch.setattr(langflow_sync, "_upsert_selected_model_variable", _noop)


class _FakeFlowsService:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def change_langflow_model_value(self, provider, **kwargs):
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
            custom={},
        ),
    )


class TestUpdateLangflowModelValuesSyncsBedrock:
    @pytest.mark.asyncio
    async def test_explicit_bedrock_embedding_provider_syncs(self):
        """Onboarding passes body.embedding_provider straight through."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("openai", "text-embedding-3-small"),
            flows,
            embedding_model="cohere.embed-multilingual-v3",
            embedding_provider="bedrock",
        )

        assert flows.calls == [
            (
                "bedrock",
                {
                    "embedding_model": "cohere.embed-multilingual-v3",
                    "force_embedding_update": True,
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_bedrock_from_config_fallback_syncs(self):
        """`update_settings` only passes the model; the provider is resolved
        from the saved config."""
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("bedrock", "cohere.embed-multilingual-v3"),
            flows,
            embedding_model="cohere.embed-multilingual-v3",
        )

        assert [provider for provider, _ in flows.calls] == ["bedrock"]

    @pytest.mark.asyncio
    async def test_llm_and_bedrock_embedding_sync_both_run(self):
        flows = _FakeFlowsService()

        await _update_langflow_model_values(
            _config("bedrock", "cohere.embed-multilingual-v3"),
            flows,
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            embedding_provider="bedrock",
            embedding_model="cohere.embed-multilingual-v3",
        )

        assert [provider for provider, _ in flows.calls] == ["openai", "bedrock"]
        assert flows.calls[0][1]["llm_model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_no_argument_reapply_includes_bedrock(self):
        """`reapply_all_settings()` calls with no models/providers; the
        configured-provider sweep must include bedrock like every other
        configured embedding provider."""
        flows = _FakeFlowsService()
        config = _config("bedrock", "cohere.embed-multilingual-v3")
        config.providers.bedrock = SimpleNamespace(configured=True)

        await _update_langflow_model_values(config, flows)

        assert "bedrock" in [provider for provider, _ in flows.calls]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
