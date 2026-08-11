"""Unit tests for Azure AI Foundry endpoint URL construction and validation."""

from api.provider_validation import _build_azure_ai_foundry_url


def test_build_azure_ai_foundry_url_base():
    endpoint = "https://my-foundry.services.ai.azure.com"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/chat/completions?api-version=2024-05-01-preview"
    )


def test_build_azure_ai_foundry_url_with_models_path():
    endpoint = "https://my-foundry.services.ai.azure.com/models"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    )


def test_build_azure_ai_foundry_url_preserves_custom_api_version():
    endpoint = "https://my-foundry.services.ai.azure.com/models?api-version=2024-08-01-preview"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-08-01-preview"
    )


def test_build_azure_ai_foundry_url_prevents_duplicate_subpath():
    endpoint = "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    )


def test_build_azure_ai_foundry_url_embeddings():
    endpoint = "https://my-foundry.services.ai.azure.com"
    url = _build_azure_ai_foundry_url(endpoint, "/embeddings")
    assert (
        url == "https://my-foundry.services.ai.azure.com/embeddings?api-version=2024-05-01-preview"
    )


def test_build_azure_ai_foundry_url_health():
    endpoint = "https://my-foundry.services.ai.azure.com/models"
    url = _build_azure_ai_foundry_url(endpoint, "")
    assert url == "https://my-foundry.services.ai.azure.com/models?api-version=2024-05-01-preview"
