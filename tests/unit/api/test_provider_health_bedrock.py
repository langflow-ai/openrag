"""Unit tests for AWS Bedrock support in the /provider/health endpoint.

Bedrock must be accepted as a valid `?provider=` query value (it was
previously rejected with a 400 "Invalid provider" response because the
endpoint's own `valid_providers` allowlist didn't know about it) and route
through to the credential-shape check without raising.
"""

import json

import pytest

from api.provider_health import check_provider_health
from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    BedrockConfig,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from utils import provider_health_cache


def _config(*, bedrock_region: str = "eu-central-1") -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(api_key="sk-test", configured=True),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            bedrock=BedrockConfig(region=bedrock_region, configured=bool(bedrock_region)),
        ),
        knowledge=KnowledgeConfig(
            embedding_model="cohere.embed-multilingual-v3",
            embedding_provider="bedrock",
        ),
        agent=AgentConfig(llm_model="gpt-5.4-mini", llm_provider="openai"),
        onboarding=OnboardingState(),
        edited=True,
    )


@pytest.fixture(autouse=True)
def _isolate_cache():
    provider_health_cache.invalidate()
    yield
    provider_health_cache.invalidate()


class TestProviderHealthAcceptsBedrock:
    @pytest.mark.asyncio
    async def test_bedrock_is_not_rejected_as_invalid_provider(self, monkeypatch):
        config = _config()
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)
        monkeypatch.setattr(
            "config.config_manager.config_manager", type("M", (), {"get_config": lambda self: config})()
        )

        response = await check_provider_health(provider="bedrock", test_completion=False)

        payload = json.loads(response.body)
        assert payload.get("message") != "Invalid provider: bedrock. Must be one of: openai, ollama, watsonx, anthropic"
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_bedrock_health_check_passes_when_region_configured(self, monkeypatch):
        config = _config(bedrock_region="eu-central-1")
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)
        monkeypatch.setattr(
            "config.config_manager.config_manager", type("M", (), {"get_config": lambda self: config})()
        )

        response = await check_provider_health(provider="bedrock", test_completion=False)

        assert response.status_code == 200
        payload = json.loads(response.body)
        assert payload["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_bedrock_health_check_fails_when_region_missing(self, monkeypatch):
        config = _config(bedrock_region="")
        monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)
        monkeypatch.setattr(
            "config.config_manager.config_manager", type("M", (), {"get_config": lambda self: config})()
        )

        response = await check_provider_health(provider="bedrock", test_completion=False)

        assert response.status_code == 503
        payload = json.loads(response.body)
        assert payload["status"] == "unhealthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
