"""
Unit tests for api.settings.langflow_sync._update_langflow_model_values

Regression tests for issue #1587: the no-argument fallback used by
reapply_all_settings (triggered when Langflow flows are detected as reset)
must reapply LLM model values for every configured LLM provider, not only
embedding providers.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.settings.langflow_sync import _update_langflow_model_values

# Providers a mock config can advertise as configured. LLM supports anthropic;
# embeddings do not, so embedding reapplication should skip it.
_ALL_PROVIDERS = ("openai", "anthropic", "watsonx", "ollama")
_EXPECTED_LLM_PROVIDERS = {"openai", "anthropic", "watsonx", "ollama"}
_EXPECTED_EMBEDDING_PROVIDERS = {"openai", "watsonx", "ollama"}


@pytest.fixture
def mock_config():
    config = MagicMock()
    for name in _ALL_PROVIDERS:
        getattr(config.providers, name).configured = True
    config.knowledge.embedding_provider = "openai"
    config.knowledge.embedding_model = "text-embedding-3-small"
    config.agent.llm_provider = "anthropic"
    config.agent.llm_model = "claude-3-5-sonnet-20241022"
    return config


def _calls_by_kwarg(flows_service, kwarg):
    """Return {provider: kwarg_value} for change_langflow_model_value calls carrying `kwarg`."""
    result = {}
    for call in flows_service.change_langflow_model_value.await_args_list:
        if kwarg in call.kwargs:
            provider = call.args[0] if call.args else call.kwargs.get("provider")
            result[provider] = call.kwargs[kwarg]
    return result


@pytest.mark.asyncio
async def test_fallback_reapplies_llm_for_all_configured_providers(mock_config):
    """No-arg fallback must call change_langflow_model_value for every configured LLM provider.

    Regression test for #1587: previously only embedding providers were reapplied,
    so LLM model values were silently dropped after a flow reset.
    """
    flows_service = MagicMock()
    flows_service.change_langflow_model_value = AsyncMock()

    # No model/provider arguments => the reapply_all_settings fallback path.
    await _update_langflow_model_values(mock_config, flows_service)

    llm_calls = _calls_by_kwarg(flows_service, "llm_model")
    assert set(llm_calls.keys()) == _EXPECTED_LLM_PROVIDERS

    # Every LLM call must force the update.
    for call in flows_service.change_langflow_model_value.await_args_list:
        if "llm_model" in call.kwargs:
            assert call.kwargs.get("force_llm_update") is True


@pytest.mark.asyncio
async def test_fallback_uses_configured_model_only_for_current_llm_provider(mock_config):
    """The active provider keeps its configured model; others reset to None (first available)."""
    flows_service = MagicMock()
    flows_service.change_langflow_model_value = AsyncMock()

    await _update_langflow_model_values(mock_config, flows_service)

    llm_calls = _calls_by_kwarg(flows_service, "llm_model")
    assert llm_calls["anthropic"] == "claude-3-5-sonnet-20241022"
    assert llm_calls["openai"] is None
    assert llm_calls["watsonx"] is None
    assert llm_calls["ollama"] is None


@pytest.mark.asyncio
async def test_fallback_still_reapplies_embedding_providers(mock_config):
    """The fix must not regress the existing embedding reapplication behavior."""
    flows_service = MagicMock()
    flows_service.change_langflow_model_value = AsyncMock()

    await _update_langflow_model_values(mock_config, flows_service)

    embedding_calls = _calls_by_kwarg(flows_service, "embedding_model")
    # anthropic is not a valid embedding provider and must be skipped.
    assert set(embedding_calls.keys()) == _EXPECTED_EMBEDDING_PROVIDERS
    assert embedding_calls["openai"] == "text-embedding-3-small"
    assert embedding_calls["watsonx"] is None
    assert embedding_calls["ollama"] is None


@pytest.mark.asyncio
async def test_fallback_only_reapplies_configured_providers(mock_config):
    """Unconfigured providers must not be touched in the fallback path."""
    mock_config.providers.watsonx.configured = False
    mock_config.providers.ollama.configured = False

    flows_service = MagicMock()
    flows_service.change_langflow_model_value = AsyncMock()

    await _update_langflow_model_values(mock_config, flows_service)

    llm_calls = _calls_by_kwarg(flows_service, "llm_model")
    assert set(llm_calls.keys()) == {"openai", "anthropic"}


@pytest.mark.asyncio
async def test_explicit_llm_arguments_bypass_fallback(mock_config):
    """When explicit llm args are passed, only that provider is updated (no fallback loop)."""
    flows_service = MagicMock()
    flows_service.change_langflow_model_value = AsyncMock()

    await _update_langflow_model_values(
        mock_config,
        flows_service,
        llm_model="gpt-4o",
        llm_provider="openai",
    )

    flows_service.change_langflow_model_value.assert_awaited_once()
    call = flows_service.change_langflow_model_value.await_args
    assert call.args[0] == "openai"
    assert call.kwargs["llm_model"] == "gpt-4o"
    assert call.kwargs.get("force_llm_update") is True
