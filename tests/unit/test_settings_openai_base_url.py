"""Tests for the OpenAI custom base URL settings write path.

Regression coverage: SettingsUpdateBody.openai_base_url and
OnboardingBody.openai_base_url were accepted by the API but never written
onto current_config.providers.openai.base_url — a client POSTing
openai_base_url got a silent no-op. See src/api/settings/endpoints.py.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

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


class _FakeTask:
    def __init__(self):
        self.done_callback = None

    def add_done_callback(self, cb):
        self.done_callback = cb


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


def _patch_update_settings_deps(monkeypatch, config):
    """Mirrors the mocking pattern used in test_settings_async_post_save.py."""
    fake_task = _FakeTask()
    saved_configs = []

    async def _noop_refresh():
        return None

    def _fake_create_task(coro):
        # We only care about the config write in these tests, not the
        # background Langflow sync that provider changes normally schedule.
        coro.close()
        return fake_task

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager,
        "save_config_file",
        lambda updated_config: saved_configs.append(updated_config) or True,
        raising=True,
    )
    monkeypatch.setattr(settings_api.clients, "refresh_patched_client", _noop_refresh, raising=True)
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(settings_api.asyncio, "create_task", _fake_create_task, raising=True)
    return fake_task, saved_configs


@pytest.mark.asyncio
async def test_update_settings_persists_openai_base_url(monkeypatch):
    settings_api._background_tasks.clear()
    config = _make_config()
    _, saved_configs = _patch_update_settings_deps(monkeypatch, config)

    response = await settings_api.update_settings(
        settings_api.SettingsUpdateBody(openai_base_url="https://gateway.example.com/v1"),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_api.SettingsUpdateResponse)
    # Mutations are staged on a deep copy and only that copy is saved; the
    # live config object passed in must never be mutated in place.
    assert saved_configs[0].providers.openai.base_url == "https://gateway.example.com/v1"
    # An optional base_url override should not, by itself, mark OpenAI as
    # "configured" the way an api_key does.
    assert saved_configs[0].providers.openai.configured is False


@pytest.mark.asyncio
async def test_update_settings_strips_openai_base_url_whitespace(monkeypatch):
    settings_api._background_tasks.clear()
    config = _make_config()
    _, saved_configs = _patch_update_settings_deps(monkeypatch, config)

    await settings_api.update_settings(
        settings_api.SettingsUpdateBody(openai_base_url="  https://gateway.example.com/v1  "),
        session_manager=object(),
        user=None,
    )

    assert saved_configs[0].providers.openai.base_url == "https://gateway.example.com/v1"


@pytest.mark.asyncio
async def test_remove_openai_config_clears_base_url(monkeypatch):
    """Regression: removing the OpenAI config used to clear api_key/configured
    but leave a stale base_url behind. A later re-enable of OpenAI would then
    silently keep routing through the old (possibly now-invalid) gateway
    instead of falling back to api.openai.com.
    """
    settings_api._background_tasks.clear()
    config = _make_config(
        openai=OpenAIConfig(
            api_key="sk-test", base_url="https://gateway.example.com/v1", configured=True
        )
    )
    # remove_openai_config requires another provider to be configured.
    config.providers.anthropic.configured = True
    _, saved_configs = _patch_update_settings_deps(monkeypatch, config)

    response = await settings_api.update_settings(
        settings_api.SettingsUpdateBody(remove_openai_config=True, force_remove=True),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_api.SettingsUpdateResponse)
    assert saved_configs[0].providers.openai.api_key == ""
    assert saved_configs[0].providers.openai.configured is False
    assert saved_configs[0].providers.openai.base_url == ""


@pytest.mark.asyncio
async def test_onboarding_persists_openai_base_url(monkeypatch):
    config = _make_config(edited=False)

    async def _noop_refresh():
        return None

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager,
        "save_config_file",
        lambda updated_config: True,
        raising=True,
    )
    monkeypatch.setattr(settings_api.clients, "refresh_patched_client", _noop_refresh, raising=True)
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(settings_api, "wait_for_langflow", AsyncMock(), raising=True)

    response = await settings_api.onboarding(
        settings_api.OnboardingBody(openai_base_url="https://gateway.example.com/v1"),
        flows_service=None,
        session_manager=object(),
        document_service=None,
        models_service=None,
        task_service=None,
        langflow_file_service=None,
        knowledge_filter_service=None,
        user=None,
    )

    assert isinstance(response, settings_api.OnboardingResponse)
    assert config.providers.openai.base_url == "https://gateway.example.com/v1"
    assert config.providers.openai.configured is False


class TestWhitespaceOnlyBaseUrlRejected:
    """A whitespace-only openai_base_url must fail validation instead of being
    silently accepted and later stripped down to an empty string by the
    endpoint handlers (which would look identical to "not configured" with
    no error surfaced to the caller).
    """

    def test_settings_update_body_rejects_whitespace_only_base_url(self):
        with pytest.raises(ValidationError):
            settings_api.SettingsUpdateBody(openai_base_url="   ")

    def test_onboarding_body_rejects_whitespace_only_base_url(self):
        with pytest.raises(ValidationError):
            settings_api.OnboardingBody(openai_base_url="   ")
