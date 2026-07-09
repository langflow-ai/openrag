"""Unit tests for the OpenAI custom base-URL override reaching the real
AsyncOpenAI client construction in `AppClients.patched_async_client`
(openrag issue #2060).

These mock the `AsyncOpenAI` constructor and `patch_openai_with_mcp` directly
so the assertion is purely "was the SDK client constructed with the right
base_url kwarg" - no network behavior involved (per task instructions).

`embedding_provider` is set to something other than "openai" so the
HTTP/2 probe thread (which only runs for provider "openai") is skipped
entirely, keeping these tests fast and deterministic. The probe path itself
is covered by the real-proxy integration test, which also exercises the
probe's own AsyncOpenAI construction against the configured base_url.
"""

import os
from unittest.mock import MagicMock

import pytest

import config.settings as settings_module
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


@pytest.fixture(autouse=True)
def _restore_environ():
    """`patched_async_client` mutates os.environ (OPENAI_API_KEY) as a real
    side effect of production code; restore it so these tests don't leak
    state into the rest of the suite."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


def _make_openrag_config(*, openai_base_url: str = "") -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(api_key="sk-test", base_url=openai_base_url, configured=True),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(
            embedding_model="text-embedding-3-small",
            embedding_provider="ollama",
        ),
        agent=AgentConfig(llm_model="gpt-5.4-mini", llm_provider="openai"),
        onboarding=OnboardingState(),
        edited=True,
    )


def _patch_client_construction(monkeypatch):
    """Replace AsyncOpenAI with a call-recording mock and no-op the MCP patch
    wrapper so we don't depend on agentd's monkey-patching internals."""
    ctor_mock = MagicMock()
    monkeypatch.setattr(settings_module, "AsyncOpenAI", ctor_mock)
    monkeypatch.setattr(settings_module, "patch_openai_with_mcp", lambda client: client)
    return ctor_mock


class TestPatchedAsyncClientBaseUrl:
    def test_constructs_with_configured_base_url(self, monkeypatch):
        fake_config = _make_openrag_config(openai_base_url="http://localhost:4444/v1")
        monkeypatch.setattr(settings_module, "get_openrag_config", lambda: fake_config)
        ctor_mock = _patch_client_construction(monkeypatch)

        app_clients = settings_module.AppClients()
        result = app_clients.patched_async_client

        assert ctor_mock.called
        assert ctor_mock.call_args.kwargs["base_url"] == "http://localhost:4444/v1"
        assert result is ctor_mock.return_value

    def test_omits_base_url_override_when_not_configured(self, monkeypatch):
        fake_config = _make_openrag_config(openai_base_url="")
        monkeypatch.setattr(settings_module, "get_openrag_config", lambda: fake_config)
        ctor_mock = _patch_client_construction(monkeypatch)

        app_clients = settings_module.AppClients()
        _ = app_clients.patched_async_client

        assert ctor_mock.called
        # None preserves the OpenAI SDK's own default-endpoint resolution
        # (falls back to the OPENAI_BASE_URL env var, then api.openai.com).
        assert ctor_mock.call_args.kwargs.get("base_url") is None

    def test_result_is_cached_on_second_access(self, monkeypatch):
        fake_config = _make_openrag_config(openai_base_url="http://localhost:4444/v1")
        monkeypatch.setattr(settings_module, "get_openrag_config", lambda: fake_config)
        ctor_mock = _patch_client_construction(monkeypatch)

        app_clients = settings_module.AppClients()
        first = app_clients.patched_async_client
        second = app_clients.patched_async_client

        assert first is second
        assert ctor_mock.call_count == 1

    def test_config_load_failure_falls_back_to_no_base_url(self, monkeypatch):
        """When config loading raises, the except-branch fallback must still
        define openai_base_url (as None) rather than raising NameError."""

        def _raise():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(settings_module, "get_openrag_config", _raise)
        ctor_mock = _patch_client_construction(monkeypatch)

        app_clients = settings_module.AppClients()
        _ = app_clients.patched_async_client

        assert ctor_mock.called
        assert ctor_mock.call_args.kwargs.get("base_url") is None
