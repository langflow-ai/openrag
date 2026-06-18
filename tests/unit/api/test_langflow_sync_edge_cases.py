"""Edge case tests for LLM fallback update in langflow_sync."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.settings.langflow_sync import _update_langflow_model_values


@pytest.mark.asyncio
async def test_empty_string_llm_provider_no_crash():
    """Empty string llm_provider should not crash and no provider receives the configured model."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = True
    mock_config.providers.watsonx.configured = False
    mock_config.providers.ollama.configured = False
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = ""  # Empty string
    mock_config.agent.llm_model = "gpt-4o"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    # Should not crash, and all LLM providers get None (no match for empty string)
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 2  # openai, anthropic
    for call in llm_calls:
        assert call.kwargs["llm_model"] is None


@pytest.mark.asyncio
async def test_llm_provider_not_in_configured_set():
    """LLM provider names a provider not in the configured set."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = False
    mock_config.providers.watsonx.configured = False
    mock_config.providers.ollama.configured = False
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = "anthropic"  # Not configured
    mock_config.agent.llm_model = "claude-3-5-sonnet-20241022"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    # Only configured providers updated, all with None (no match)
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 1  # Only openai
    assert llm_calls[0].args[0] == "openai"
    assert llm_calls[0].kwargs["llm_model"] is None


@pytest.mark.asyncio
async def test_single_configured_provider():
    """Single configured provider works correctly."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = False
    mock_config.providers.anthropic.configured = False
    mock_config.providers.watsonx.configured = True
    mock_config.providers.ollama.configured = False
    mock_config.knowledge.embedding_provider = "watsonx"
    mock_config.knowledge.embedding_model = "ibm/granite-embedding-125m-english"
    mock_config.agent.llm_provider = "watsonx"
    mock_config.agent.llm_model = "ibm/granite-3-8b-instruct"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 1
    assert llm_calls[0].args[0] == "watsonx"
    assert llm_calls[0].kwargs["llm_model"] == "ibm/granite-3-8b-instruct"


@pytest.mark.asyncio
async def test_provider_list_consistency():
    """LLM set has 4 entries, embedding set has 3 (no anthropic)."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = True
    mock_config.providers.watsonx.configured = True
    mock_config.providers.ollama.configured = True
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = "openai"
    mock_config.agent.llm_model = "gpt-4o"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model=None,
        llm_provider=None,
        embedding_model=None,
        embedding_provider=None,
    )

    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    embedding_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_embedding_update" in call.kwargs
    ]

    assert len(llm_calls) == 4  # openai, anthropic, watsonx, ollama
    assert len(embedding_calls) == 3  # openai, watsonx, ollama (no anthropic)

    llm_providers = {call.args[0] for call in llm_calls}
    embedding_providers = {call.args[0] for call in embedding_calls}

    assert llm_providers == {"openai", "anthropic", "watsonx", "ollama"}
    assert embedding_providers == {"openai", "watsonx", "ollama"}
    assert "anthropic" not in embedding_providers


@pytest.mark.asyncio
async def test_exception_mid_loop_propagates():
    """Exception mid-loop propagates (matches embedding loop behavior)."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = True
    mock_config.providers.watsonx.configured = True
    mock_config.providers.ollama.configured = True
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = "openai"
    mock_config.agent.llm_model = "gpt-4o"

    mock_flows_service = AsyncMock()
    # Fail on the second LLM call
    call_count = [0]

    async def side_effect(*args, **kwargs):
        if "force_llm_update" in kwargs:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Simulated failure")
        return {"updated": True}

    mock_flows_service.change_langflow_model_value = AsyncMock(side_effect=side_effect)

    with pytest.raises(RuntimeError, match="Simulated failure"):
        await _update_langflow_model_values(
            mock_config,
            mock_flows_service,
            llm_model=None,
            llm_provider=None,
            embedding_model=None,
            embedding_provider=None,
        )


@pytest.mark.asyncio
async def test_explicit_overrides_skip_fallback():
    """Explicit overrides passed means fallback branch NOT reached."""
    mock_config = MagicMock()
    mock_config.providers.openai.configured = True
    mock_config.providers.anthropic.configured = True
    mock_config.providers.watsonx.configured = True
    mock_config.providers.ollama.configured = True
    mock_config.knowledge.embedding_provider = "openai"
    mock_config.knowledge.embedding_model = "text-embedding-3-small"
    mock_config.agent.llm_provider = "anthropic"
    mock_config.agent.llm_model = "claude-3-5-sonnet-20241022"

    mock_flows_service = AsyncMock()
    mock_flows_service.change_langflow_model_value = AsyncMock(return_value={"updated": True})

    # Pass explicit LLM override
    await _update_langflow_model_values(
        mock_config,
        mock_flows_service,
        llm_model="gpt-4o",
        llm_provider="openai",
        embedding_model=None,
        embedding_provider=None,
    )

    # Should only have 1 LLM call (the explicit override), not 4 from fallback
    llm_calls = [
        call
        for call in mock_flows_service.change_langflow_model_value.call_args_list
        if "force_llm_update" in call.kwargs
    ]
    assert len(llm_calls) == 1
    assert llm_calls[0].args[0] == "openai"
    assert llm_calls[0].kwargs["llm_model"] == "gpt-4o"
