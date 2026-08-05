"""Regression coverage: update_settings/onboarding must forward the OpenAI
base-URL override into validate_provider_setup's "endpoint" argument when
openai is the (or becomes the) llm/embedding provider.

Before this fix, `endpoint = getattr(llm_provider_config, "endpoint", None)`
was always None for openai (OpenAIConfig has no "endpoint" attribute, only
"base_url"), so validate_provider_setup always fell through to validating
against the real OpenAI API - rejecting a gateway-only key with a 400 even
when openai_base_url was configured correctly. See
src/api/settings/endpoints.py and src/api/provider_validation.py.
"""

from unittest.mock import AsyncMock

import pytest

import api.settings.endpoints as settings_api
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

GATEWAY_URL = "http://localhost:4444/v1"


class _FakeTask:
    def add_done_callback(self, cb):
        pass


def _make_config(*, edited: bool = True, openai: OpenAIConfig | None = None) -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=openai if openai is not None else OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(),
        agent=AgentConfig(),
        onboarding=OnboardingState(),
        edited=edited,
    )


def _patch_update_settings_deps(monkeypatch, config, validate_mock):
    saved_configs = []

    async def _noop_refresh():
        return None

    def _fake_create_task(coro):
        coro.close()
        return _FakeTask()

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(settings_api, "validate_provider_setup", validate_mock, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager,
        "save_config_file",
        lambda updated_config: saved_configs.append(updated_config) or True,
        raising=True,
    )
    monkeypatch.setattr(settings_api.clients, "refresh_patched_client", _noop_refresh, raising=True)
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(settings_api.asyncio, "create_task", _fake_create_task, raising=True)
    return saved_configs


@pytest.mark.asyncio
async def test_update_settings_llm_provider_validates_against_configured_base_url(monkeypatch):
    """openai_base_url set in the same request as switching llm_provider to
    openai must reach validate_provider_setup's endpoint kwarg (the body
    hasn't been persisted to config yet at validation time)."""
    settings_api._background_tasks.clear()
    config = _make_config(openai=OpenAIConfig(api_key="sk-gateway-key"))
    validate_mock = AsyncMock()
    _patch_update_settings_deps(monkeypatch, config, validate_mock)

    await settings_api.update_settings(
        settings_api.SettingsUpdateBody(
            llm_provider="openai",
            llm_model="cohere-embed-multilingual-bedrock",
            openai_base_url=GATEWAY_URL,
        ),
        session_manager=object(),
        user=None,
    )

    llm_calls = [c for c in validate_mock.await_args_list if c.kwargs.get("llm_model")]
    assert llm_calls, f"validate_provider_setup never called with llm_model: {validate_mock.await_args_list}"
    assert llm_calls[0].kwargs["provider"] == "openai"
    assert llm_calls[0].kwargs["endpoint"] == GATEWAY_URL


@pytest.mark.asyncio
async def test_update_settings_embedding_provider_validates_against_already_saved_base_url(
    monkeypatch,
):
    """A previously-saved base_url (not part of this request's body) must
    still be picked up from the provider config when only the embedding
    model/provider is being changed."""
    settings_api._background_tasks.clear()
    config = _make_config(
        openai=OpenAIConfig(api_key="sk-gateway-key", base_url=GATEWAY_URL, configured=True)
    )
    validate_mock = AsyncMock()
    _patch_update_settings_deps(monkeypatch, config, validate_mock)

    await settings_api.update_settings(
        settings_api.SettingsUpdateBody(
            embedding_provider="openai",
            embedding_model="cohere-embed-multilingual-bedrock",
        ),
        session_manager=object(),
        user=None,
    )

    embedding_calls = [
        c for c in validate_mock.await_args_list if c.kwargs.get("embedding_model")
    ]
    assert embedding_calls, f"validate_provider_setup never called with embedding_model: {validate_mock.await_args_list}"
    assert embedding_calls[0].kwargs["provider"] == "openai"
    assert embedding_calls[0].kwargs["endpoint"] == GATEWAY_URL


@pytest.mark.asyncio
async def test_onboarding_validates_against_configured_base_url(monkeypatch):
    """current_config is mutated with openai_base_url before the onboarding
    validation block runs, so the saved base_url must reach
    validate_provider_setup's endpoint kwarg."""
    config = _make_config(edited=False)
    validate_mock = AsyncMock()

    async def _noop_refresh():
        return None

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(settings_api, "validate_provider_setup", validate_mock, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager, "save_config_file", lambda updated_config: True, raising=True
    )
    monkeypatch.setattr(settings_api.clients, "refresh_patched_client", _noop_refresh, raising=True)
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(settings_api, "wait_for_langflow", AsyncMock(), raising=True)

    await settings_api.onboarding(
        settings_api.OnboardingBody(
            llm_provider="openai",
            llm_model="cohere-embed-multilingual-bedrock",
            openai_api_key="sk-gateway-key",
            openai_base_url=GATEWAY_URL,
        ),
        flows_service=None,
        session_manager=object(),
        document_service=None,
        models_service=None,
        task_service=None,
        langflow_file_service=None,
        knowledge_filter_service=None,
        user=None,
    )

    llm_calls = [c for c in validate_mock.await_args_list if c.kwargs.get("llm_model")]
    assert llm_calls, f"validate_provider_setup never called with llm_model: {validate_mock.await_args_list}"
    assert llm_calls[0].kwargs["provider"] == "openai"
    assert llm_calls[0].kwargs["endpoint"] == GATEWAY_URL
