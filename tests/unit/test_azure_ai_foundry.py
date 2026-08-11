"""Unit tests for Azure AI Foundry endpoint URL construction and validation."""

from api.provider_validation import _build_azure_ai_foundry_url


def test_build_azure_ai_foundry_url_base():
    # LiteLLM's azure_ai handler always inserts a /models segment for any
    # services.ai.azure.com host, regardless of what's already in api_base.
    endpoint = "https://my-foundry.services.ai.azure.com"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_project_endpoint():
    # "Microsoft Foundry" project-style endpoints have no flat /chat/completions
    # route — only /<project>/models/chat/completions resolves (404 otherwise).
    endpoint = "https://my-foundry.services.ai.azure.com/api/projects/my-project"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert url == (
        "https://my-foundry.services.ai.azure.com"
        "/api/projects/my-project/models/chat/completions"
        "?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_project_endpoint_health():
    endpoint = "https://my-foundry.services.ai.azure.com/api/projects/my-project"
    url = _build_azure_ai_foundry_url(endpoint)
    assert url == (
        "https://my-foundry.services.ai.azure.com"
        "/api/projects/my-project/models"
        "?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_with_models_path():
    endpoint = "https://my-foundry.services.ai.azure.com/models"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_preserves_custom_api_version():
    endpoint = "https://my-foundry.services.ai.azure.com/models?api-version=2024-08-01-preview"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-08-01-preview"
    )


def test_build_azure_ai_foundry_url_prevents_duplicate_subpath():
    endpoint = (
        "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2025-04-01"
    )
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert (
        url
        == "https://my-foundry.services.ai.azure.com/models/chat/completions?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_embeddings():
    endpoint = "https://my-foundry.services.ai.azure.com"
    url = _build_azure_ai_foundry_url(endpoint, "/embeddings")
    assert url == (
        "https://my-foundry.services.ai.azure.com/models/embeddings?api-version=2025-04-01"
    )


def test_build_azure_ai_foundry_url_health():
    endpoint = "https://my-foundry.services.ai.azure.com/models"
    url = _build_azure_ai_foundry_url(endpoint, "")
    assert url == "https://my-foundry.services.ai.azure.com/models?api-version=2025-04-01"


# --- OpenAI-compatible /openai/v1 form: no /models segment, no dated api-version ---
# (Azure's own docs: "api-version is no longer a required parameter with the v1
# GA API." A dated version here 404s on the /models-prefixed path we used to
# build, since that route doesn't exist for this endpoint form.)


def test_build_azure_ai_foundry_url_openai_v1_chat():
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions")
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1/chat/completions"


def test_build_azure_ai_foundry_url_openai_v1_embeddings():
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    url = _build_azure_ai_foundry_url(endpoint, "/embeddings")
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1/embeddings"


def test_build_azure_ai_foundry_url_openai_v1_health_probes_models():
    # Blank target_subpath (the credential health-check probe) lists models
    # rather than hitting the bare /openai/v1 root.
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    url = _build_azure_ai_foundry_url(endpoint)
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1/models"


def test_build_azure_ai_foundry_url_openai_v1_ignores_dated_api_version():
    # A dated api_version (from a saved config that predates this fix, or one
    # meant for the generic /models form) must never reach the v1 route — it
    # only accepts the literal "v1"/"preview" values, never a dated string.
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    url = _build_azure_ai_foundry_url(endpoint, "/chat/completions", api_version="2025-04-01")
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1/chat/completions"


def test_build_azure_ai_foundry_url_openai_v1_preserves_literal_api_version():
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1?api-version=preview"
    url = _build_azure_ai_foundry_url(endpoint, "/models")
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1/models?api-version=preview"
