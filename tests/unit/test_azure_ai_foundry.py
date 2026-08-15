"""Unit tests for Azure AI Foundry endpoint URL construction and validation."""

import pytest

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


@pytest.mark.asyncio
async def test_azure_ai_foundry_litellm_model_name_routing():
    from config.config_manager import (
        AnthropicConfig,
        AzureAIFoundryConfig,
        OllamaConfig,
        OpenAIConfig,
        ProvidersConfig,
        WatsonXConfig,
    )
    from services.models_service import ModelsService

    service = ModelsService()

    def providers_config(azure_ai_foundry: AzureAIFoundryConfig) -> ProvidersConfig:
        return ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            azure_ai_foundry=azure_ai_foundry,
        )

    class FakeConfigManager:
        def __init__(self, providers: ProvidersConfig):
            self._providers = providers

        def get_config(self):
            class Config:
                pass

            config = Config()
            config.providers = self._providers
            return config

    # Case 1: .openai.azure.com endpoint routes to azure/{model_name}
    cfg1 = providers_config(
        AzureAIFoundryConfig(
            endpoint="https://my-resource.openai.azure.com",
            llm_deployment_name="gpt-4o",
        )
    )
    service._config_manager = FakeConfigManager(cfg1)
    assert await service.get_litellm_model_name("gpt-4o", "azure_ai_foundry") == "azure/gpt-4o"

    # Case 2: Serverless/Foundry endpoint routes to azure_ai/{model_name}
    cfg2 = providers_config(
        AzureAIFoundryConfig(
            endpoint="https://my-foundry.services.ai.azure.com",
            llm_deployment_name="deepseek-r1",
        )
    )
    service._config_manager = FakeConfigManager(cfg2)
    assert (
        await service.get_litellm_model_name("deepseek-r1", "azure_ai_foundry")
        == "azure_ai/deepseek-r1"
    )

    # Case 3: the OpenAI-compatible /openai/v1 endpoint must NOT use azure_ai/
    # — LiteLLM's azure_ai handler builds
    # ".../openai/v1/openai/deployments/<model>/embeddings", which 404s
    # ("Resource not found"). The plain openai provider + api_base hits
    # ".../openai/v1/embeddings", the route this form actually serves.
    cfg3 = providers_config(
        AzureAIFoundryConfig(
            endpoint="https://my-foundry.services.ai.azure.com/openai/v1",
            embedding_deployment_name="text-embedding-3-small",
        )
    )
    service._config_manager = FakeConfigManager(cfg3)
    assert (
        await service.get_litellm_model_name("text-embedding-3-small", "azure_ai_foundry")
        == "openai/text-embedding-3-small"
    )


def test_is_azure_ai_foundry_openai_v1_endpoint():
    from api.provider_validation import is_azure_ai_foundry_openai_v1_endpoint

    assert is_azure_ai_foundry_openai_v1_endpoint(
        "https://my-foundry.services.ai.azure.com/openai/v1"
    )
    assert is_azure_ai_foundry_openai_v1_endpoint(
        "https://my-foundry.services.ai.azure.com/openai/v1/"
    )
    assert not is_azure_ai_foundry_openai_v1_endpoint("https://my-foundry.services.ai.azure.com")
    assert not is_azure_ai_foundry_openai_v1_endpoint(
        "https://my-foundry.services.ai.azure.com/api/projects/proj"
    )
    assert not is_azure_ai_foundry_openai_v1_endpoint("")


def test_build_azure_ai_foundry_url_openai_v1_bare_root_for_api_base():
    # target_subpath=None asks for the true bare root, distinct from "" (which
    # means "list models"). Used for AZURE_AI_API_BASE / the LiteLLM api_base,
    # where the caller appends its own /embeddings and a baked-in /models would
    # produce ".../openai/v1/models/embeddings" and 404.
    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    url = _build_azure_ai_foundry_url(endpoint, target_subpath=None)
    assert url == "https://my-foundry.services.ai.azure.com/openai/v1"


@pytest.mark.asyncio
async def test_azure_ai_foundry_completion_uses_max_completion_tokens(monkeypatch):
    from api import provider_validation

    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(provider_validation.httpx, "AsyncClient", FakeAsyncClient)

    await provider_validation._test_azure_ai_foundry_completion(
        "key",
        "gpt-5-nano",
        "https://my-foundry.services.ai.azure.com",
    )

    payload = captured["json"]
    assert payload["max_completion_tokens"] == 10
    assert "max_tokens" not in payload


def _chat_config(llm_provider: str, llm_model: str, endpoint: str = ""):
    """Minimal config stand-in for ChatService._resolve_llm_model."""
    from config.config_manager import AzureAIFoundryConfig

    class Agent:
        pass

    class Providers:
        pass

    class Config:
        pass

    agent = Agent()
    agent.llm_provider = llm_provider
    agent.llm_model = llm_model

    providers = Providers()
    providers.azure_ai_foundry = AzureAIFoundryConfig(endpoint=endpoint)

    config = Config()
    config.agent = agent
    config.providers = providers
    return config


@pytest.mark.asyncio
async def test_chat_uses_configured_azure_model(monkeypatch):
    """Chat must route to the configured provider, not a hardcoded OpenAI model.

    A bare/unprefixed name is what makes agentd fall through to api.openai.com,
    which is how an Azure-only install ends up billing OpenAI.
    """
    import config.settings as settings
    from services.chat_service import ChatService
    from services.models_service import ModelsService

    endpoint = "https://my-foundry.services.ai.azure.com"
    config = _chat_config("azure_ai_foundry", "Phi-4-mini-instruct", endpoint)
    monkeypatch.setattr(settings, "get_openrag_config", lambda: config)

    service = ChatService(models_service=ModelsService())
    assert await service._resolve_llm_model() == "azure_ai/Phi-4-mini-instruct"


@pytest.mark.asyncio
async def test_chat_strips_openai_prefix_for_foundry_v1(monkeypatch):
    """On the openai/v1 endpoint the wire name must be the bare deployment.

    agentd hands "openai"-provider models to the OpenAI SDK client verbatim, and
    Foundry rejects "openai/<deployment>" with DeploymentNotFound. The endpoint
    is supplied by clients.patched_llm_client instead.
    """
    import litellm.utils as llm_utils

    import config.settings as settings
    from services.chat_service import ChatService
    from services.models_service import ModelsService

    endpoint = "https://my-foundry.services.ai.azure.com/openai/v1"
    config = _chat_config("azure_ai_foundry", "Phi-4-mini-instruct", endpoint)
    monkeypatch.setattr(settings, "get_openrag_config", lambda: config)

    service = ChatService(models_service=ModelsService())
    resolved = await service._resolve_llm_model()

    assert resolved == "Phi-4-mini-instruct"
    # Still routable: agentd resolves the provider off this name, and an
    # unregistered bare name would raise instead of answering "openai".
    assert llm_utils.get_llm_provider(resolved)[1] == "openai"


@pytest.mark.asyncio
async def test_chat_openai_provider_is_unchanged(monkeypatch):
    import config.settings as settings
    from services.chat_service import ChatService
    from services.models_service import ModelsService

    config = _chat_config("openai", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "get_openrag_config", lambda: config)

    service = ChatService(models_service=ModelsService())
    assert await service._resolve_llm_model() == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_chat_without_configured_model_fails_loudly(monkeypatch):
    """No model configured must raise, not silently fall back to an OpenAI default."""
    import config.settings as settings
    from services.chat_service import ChatService
    from services.models_service import ModelsService

    config = _chat_config("azure_ai_foundry", "")
    monkeypatch.setattr(settings, "get_openrag_config", lambda: config)

    service = ChatService(models_service=ModelsService())
    with pytest.raises(ValueError, match="No LLM model is configured"):
        await service._resolve_llm_model()
