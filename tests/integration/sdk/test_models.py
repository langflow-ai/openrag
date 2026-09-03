"""Tests for the models endpoint."""

import os

import pytest
from openrag_sdk.exceptions import ValidationError

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)

ALL_PROVIDERS = ("azure", "openai", "anthropic", "ollama", "watsonx")


def _get_primary_provider() -> str:
    if (
        os.getenv("AZURE_OPENAI_API_KEY")
        or os.getenv("AZURE_API_KEY")
        or os.getenv("LLM_PROVIDER") == "azure"
    ):
        return "azure"
    return "openai"


class TestModels:
    """Test model listing per provider."""

    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """Listing models for a provider must return language and embedding model lists.

        The primary configured provider (azure or openai) is guaranteed to be
        configured by the test onboarding fixture (conftest.ensure_onboarding).
        The other providers are covered defensively in test_list_models_all_providers below.
        """
        primary = _get_primary_provider()
        models = await client.models.list(primary)

        assert models.language_models is not None
        assert isinstance(models.language_models, list)
        assert models.embedding_models is not None
        assert isinstance(models.embedding_models, list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ALL_PROVIDERS)
    async def test_list_models_per_provider(self, client, provider):
        """List models for each supported provider.

        The primary provider is required to be configured. Any other provider
        that isn't configured on this instance raises ValidationError (HTTP 400)
        and is marked as explicitly skipped.
        """
        primary = _get_primary_provider()
        try:
            models = await client.models.list(provider)
        except ValidationError:
            if provider == primary:
                raise
            pytest.skip(f"provider '{provider}' is not configured on this instance")

        assert isinstance(models.language_models, list)
        assert isinstance(models.embedding_models, list)

        if models.language_models:
            first = models.language_models[0]
            assert isinstance(first.value, str)
            defaults = [m for m in models.language_models if m.default is True]
            assert len(defaults) <= 1, (
                f"Provider {provider} returned more than one default language model"
            )
            assert len(defaults) >= 1, (
                f"Provider {provider} has language models but none marked default"
            )

    @pytest.mark.asyncio
    async def test_list_models_invalid_provider_raises_validation_error(self, client):
        """Listing models for an unrecognized provider must raise ValidationError."""
        with pytest.raises(ValidationError):
            await client.models.list("invalid_provider")
