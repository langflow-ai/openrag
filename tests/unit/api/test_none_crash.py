"""Test that None llm_provider is handled gracefully without AttributeError."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.settings.langflow_sync import _update_langflow_model_values


@pytest.mark.asyncio
async def test_none_llm_provider_handled_gracefully():
    """
    config.agent.llm_provider = None should not crash with AttributeError.

    The schema types the field as str, but dataclasses don't enforce non-None at runtime.
    The fix adds `or ""` guard before calling .lower() to prevent AttributeError.
    """
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = True
    mock_config.providers.watsonx.configured = False
    mock_config.providers.ollama.configured = False
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = None  # None instead of string
    mock_config.agent.llm_model = "gpt-4o"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    # Should not raise AttributeError
    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    # All providers should receive None model values (no match for empty string from None)
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 2  # openai, anthropic
    for call in llm_calls:
        assert call.kwargs["llm_model"] is None
