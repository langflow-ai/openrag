"""Regression coverage: GET /api/provider/health must forward the configured
OpenAI base-URL override into validate_provider_setup's "endpoint" argument.

Before this fix, both branches of check_provider_health() did
`endpoint = getattr(provider_config, "endpoint", None)`, which is always None
for openai (OpenAIConfig has no "endpoint" attribute, only "base_url"). That
made the health check validate against the real OpenAI API even when a
custom gateway was configured, surfacing a false "Incorrect API key
provided" banner for a working gateway-only key. See
src/api/settings/endpoints.py for the same fix already applied to
update_settings/onboarding, and tests/unit/test_settings_openai_base_url_validation.py.
"""

from unittest.mock import AsyncMock

import pytest

import api.provider_health as provider_health_api
from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from utils import provider_health_cache

GATEWAY_URL = "http://localhost:4444/v1"


def _make_config(*, llm_provider="openai", embedding_provider="openai") -> OpenRAGConfig:
    config = OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(api_key="sk-gateway-key", base_url=GATEWAY_URL, configured=True),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(),
        agent=AgentConfig(),
        onboarding=OnboardingState(),
        edited=True,
    )
    config.agent.llm_provider = llm_provider
    config.agent.llm_model = "stub-chat-model"
    config.knowledge.embedding_provider = embedding_provider
    config.knowledge.embedding_model = "stub-embed-model"
    return config


@pytest.mark.asyncio
async def test_check_specific_provider_validates_against_configured_base_url(monkeypatch):
    """GET /api/provider/health?provider=openai must resolve base_url."""
    config = _make_config()
    validate_mock = AsyncMock()
    monkeypatch.setattr(
        provider_health_api, "get_openrag_config", lambda: config, raising=True
    )
    monkeypatch.setattr(
        provider_health_api, "validate_provider_setup", validate_mock, raising=True
    )

    await provider_health_api.check_provider_health(provider="openai", user=None)

    validate_mock.assert_awaited_once()
    call = validate_mock.await_args
    assert call.kwargs["provider"] == "openai"
    assert call.kwargs["endpoint"] == GATEWAY_URL


@pytest.mark.asyncio
async def test_check_both_providers_validates_against_configured_base_url(monkeypatch):
    """The default (no ?provider=) poll path must also resolve base_url for
    both the LLM and embedding provider slots."""
    provider_health_cache.invalidate()
    config = _make_config()
    validate_mock = AsyncMock()
    monkeypatch.setattr(
        provider_health_api, "get_openrag_config", lambda: config, raising=True
    )
    monkeypatch.setattr(
        provider_health_api, "validate_provider_setup", validate_mock, raising=True
    )

    await provider_health_api.check_provider_health(user=None)

    assert validate_mock.await_count == 2
    for call in validate_mock.await_args_list:
        assert call.kwargs["provider"] == "openai"
        assert call.kwargs["endpoint"] == GATEWAY_URL
