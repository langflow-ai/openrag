"""Tests for the models endpoint."""

import os

import pytest
from openrag_sdk.exceptions import ValidationError

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)

ALL_PROVIDERS = ("openai", "anthropic", "ollama", "watsonx")


class TestModels:
    """Test model listing per provider."""

    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """Listing models for a provider must return language and embedding model lists.

        Only `openai` is guaranteed to be configured by the test onboarding
        fixture (conftest.ensure_onboarding). The other providers are covered
        defensively in test_list_models_all_providers below, since a typical
        local dev instance may not have anthropic/ollama/watsonx configured —
        the server responds with a 400 (ValidationError) in that case, not an
        empty list.
        """
        models = await client.models.list("openai")

        assert models.language_models is not None
        assert isinstance(models.language_models, list)
        assert models.embedding_models is not None
        assert isinstance(models.embedding_models, list)

    @pytest.mark.asyncio
    async def test_list_models_all_providers(self, client):
        """List models for every supported provider.

        A provider that isn't configured server-side raises ValidationError
        (HTTP 400) rather than returning an empty list, so unconfigured
        providers are skipped narrowly rather than failing the test.
        """
        checked_any = False

        for provider in ALL_PROVIDERS:
            try:
                models = await client.models.list(provider)
            except ValidationError:
                # Provider not configured on this instance (missing API key /
                # endpoint / project id) — expected on a typical local dev
                # setup for providers other than the onboarded one.
                continue

            checked_any = True
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

        assert checked_any, "No provider was configured — could not verify models.list() shape"

    @pytest.mark.asyncio
    async def test_list_models_invalid_provider_raises_validation_error(self, client):
        """Listing models for an unrecognized provider must raise ValidationError."""
        with pytest.raises(ValidationError):
            await client.models.list("invalid_provider")
