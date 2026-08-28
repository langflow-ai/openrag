"""Unit tests for AWS Bedrock support in the settings Pydantic models and
provider-name helpers (api.settings.models / api.settings.helpers).
"""

from types import SimpleNamespace

import pytest

from api.settings.helpers import (
    _EMBEDDING_PROVIDER_NAMES,
    _first_configured_embedding_provider,
)
from api.settings.models import (
    AnthropicProviderConfig,
    BedrockProviderConfig,
    OllamaProviderConfig,
    OnboardingBody,
    OpenAIProviderConfig,
    ProvidersConfig,
    SettingsUpdateBody,
    WatsonXProviderConfig,
)


class TestEmbeddingProviderRegexAcceptsBedrock:
    def test_settings_update_body_accepts_bedrock(self):
        body = SettingsUpdateBody(embedding_provider="bedrock")
        assert body.embedding_provider == "bedrock"

    def test_onboarding_body_accepts_bedrock(self):
        body = OnboardingBody(embedding_provider="bedrock")
        assert body.embedding_provider == "bedrock"


class TestEmbeddingProviderNamesIncludesBedrock:
    def test_bedrock_in_embedding_provider_names(self):
        """_EMBEDDING_PROVIDER_NAMES is the single provider-agnostic list
        used for both fallback selection and Langflow flow syncing -
        change_langflow_model_value() proxies every provider through the
        same OpenRAG-internal endpoint, so bedrock belongs here just like
        openai/watsonx/ollama."""
        assert "bedrock" in _EMBEDDING_PROVIDER_NAMES

    def test_first_configured_embedding_provider_finds_bedrock(self):
        config = SimpleNamespace(
            providers=SimpleNamespace(
                openai=SimpleNamespace(configured=False),
                watsonx=SimpleNamespace(configured=False),
                ollama=SimpleNamespace(configured=False),
                bedrock=SimpleNamespace(configured=True),
                custom={},
            )
        )

        assert _first_configured_embedding_provider(config, excluding="openai") == "bedrock"

    def test_first_configured_embedding_provider_skips_excluded_bedrock(self):
        config = SimpleNamespace(
            providers=SimpleNamespace(
                openai=SimpleNamespace(configured=False),
                watsonx=SimpleNamespace(configured=False),
                ollama=SimpleNamespace(configured=False),
                bedrock=SimpleNamespace(configured=True),
                custom={},
            )
        )

        assert _first_configured_embedding_provider(config, excluding="bedrock") == ""


class TestBedrockProviderConfigResponseModel:
    def test_shape_mirrors_watsonx_provider_config(self):
        model = BedrockProviderConfig(has_access_key=True, region="eu-central-1", configured=True)
        assert model.has_access_key is True
        assert model.region == "eu-central-1"
        assert model.configured is True

    def test_region_is_optional(self):
        model = BedrockProviderConfig(has_access_key=False, region=None, configured=False)
        assert model.region is None

    def test_providers_config_bedrock_field_defaults_to_none(self):
        """get_settings() in api/settings/endpoints.py doesn't populate this
        yet (see follow-up notes) - it must default to None so the response
        model stays constructible without changes there."""
        providers = ProvidersConfig(
            openai=OpenAIProviderConfig(has_api_key=False, configured=False),
            anthropic=AnthropicProviderConfig(has_api_key=False, configured=False),
            watsonx=WatsonXProviderConfig(
                has_api_key=False, endpoint=None, project_id=None, configured=False
            ),
            ollama=OllamaProviderConfig(endpoint=None, configured=False),
        )
        assert providers.bedrock is None

    def test_providers_config_accepts_explicit_bedrock(self):
        providers = ProvidersConfig(
            openai=OpenAIProviderConfig(has_api_key=False, configured=False),
            anthropic=AnthropicProviderConfig(has_api_key=False, configured=False),
            watsonx=WatsonXProviderConfig(
                has_api_key=False, endpoint=None, project_id=None, configured=False
            ),
            ollama=OllamaProviderConfig(endpoint=None, configured=False),
            bedrock=BedrockProviderConfig(has_access_key=True, region="us-east-1", configured=True),
        )
        assert providers.bedrock.region == "us-east-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
