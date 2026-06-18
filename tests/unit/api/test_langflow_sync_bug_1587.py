"""Tests for bug #1587: LLM model values not restored by fallback branch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.settings.langflow_sync import _update_langflow_model_values


@pytest.fixture
def mock_config():
    """Standard mock configuration for langflow sync tests.

    All four providers configured; embedding via openai, LLM via anthropic.
    """
    config = MagicMock()
    config.providers.openai.configured = True
    config.providers.anthropic.configured = True
    config.providers.watsonx.configured = True
    config.providers.ollama.configured = True
    config.knowledge.embedding_provider = "openai"
    config.knowledge.embedding_model = "text-embedding-3-small"
    config.agent.llm_provider = "anthropic"
    config.agent.llm_model = "claude-3-5-sonnet-20241022"
    return config


@pytest.fixture
def mock_flows_service():
    """Flows service stub whose model-value calls report a successful update."""
    service = AsyncMock()
    service.change_langflow_model_value = AsyncMock(return_value={"updated": True})
    return service


@pytest.mark.asyncio
@pytest.mark.skip(reason="Documents pre-fix behavior of #1587; fails by design on fixed code")
async def test_bug_1587_unfixed_no_llm_updates_in_fallback(mock_config, mock_flows_service):
    """
    Demonstrates the bug: when reapply_all_settings() calls _update_langflow_model_values()
    with no explicit overrides, the fallback branch updates embedding providers but NOT
    LLM providers, leaving flows in a reset state.

    This test is skipped because it documents the UNFIXED behavior and will fail on fixed code.
    """
    # Call with no explicit overrides (the reapply_all_settings path)
    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    # On unfixed code: zero LLM calls, only embedding calls
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "llm_model" in call.kwargs or "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 0, "Bug #1587: fallback branch should update LLM providers but doesn't"


@pytest.mark.asyncio
async def test_bug_1587_fixed_llm_updates_in_fallback(mock_config, mock_flows_service):
    """
    Validates the fix: when reapply_all_settings() calls _update_langflow_model_values()
    with no explicit overrides, the fallback branch now updates BOTH LLM and embedding
    providers across all configured providers.
    """
    # Call with no explicit overrides (the reapply_all_settings path)
    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    # Verify LLM calls
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs and call.kwargs["force_llm_update"] is True
    ]
    assert len(llm_calls) == 4, (
        "Should update all 4 LLM providers (openai, anthropic, watsonx, ollama)"
    )

    # Verify current provider gets the configured model
    anthropic_call = next((call for call in llm_calls if call.args[0] == "anthropic"), None)
    assert anthropic_call is not None
    assert anthropic_call.kwargs["llm_model"] == "claude-3-5-sonnet-20241022"

    # Verify other providers get None
    for provider in ["openai", "watsonx", "ollama"]:
        provider_call = next((call for call in llm_calls if call.args[0] == provider), None)
        assert provider_call is not None
        assert provider_call.kwargs["llm_model"] is None

    # Verify embedding calls unchanged (3 providers: openai, watsonx, ollama - no anthropic)
    embedding_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_embedding_update" in call.kwargs and call.kwargs["force_embedding_update"] is True
    ]
    assert len(embedding_calls) == 3
