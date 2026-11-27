"""Coverage for the OpenAI custom base-URL override (openrag issue #2060).

`OpenAIConfig.base_url` lets OpenRAG be pointed at a self-hosted
OpenAI-compatible gateway (e.g. a LiteLLM proxy) instead of api.openai.com.
These tests pin the config-layer plumbing: the dataclass field itself, the
`OPENAI_BASE_URL` env-override, and that `get_provider_config("openai")`
still returns a usable object with the new field attached.
"""

import tempfile
from pathlib import Path

import pytest

from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    ConfigManager,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)


def _make_config(*, openai_base_url: str = "") -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(api_key="sk-test", base_url=openai_base_url, configured=True),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(),
        agent=AgentConfig(),
        onboarding=OnboardingState(),
        edited=True,
    )


class TestOpenAIConfigDataclass:
    def test_defaults_to_empty_string(self):
        cfg = OpenAIConfig()
        assert cfg.base_url == ""

    def test_accepts_base_url_kwarg(self):
        cfg = OpenAIConfig(api_key="sk-test", base_url="http://localhost:4444/v1", configured=True)
        assert cfg.base_url == "http://localhost:4444/v1"

    def test_round_trips_through_to_dict_and_from_dict(self):
        config = _make_config(openai_base_url="http://localhost:4444/v1")
        data = config.to_dict()
        assert data["providers"]["openai"]["base_url"] == "http://localhost:4444/v1"

        # from_dict decrypts api_key; give it an already-"plaintext" key so the
        # round trip doesn't depend on encryption/master-secret state.
        rebuilt = OpenRAGConfig.from_dict(data)
        assert rebuilt.providers.openai.base_url == "http://localhost:4444/v1"


class TestGetProviderConfig:
    def test_get_provider_config_exposes_base_url(self):
        config = _make_config(openai_base_url="http://localhost:4444/v1")
        provider_config = config.providers.get_provider_config("openai")
        assert provider_config is config.providers.openai
        assert provider_config.base_url == "http://localhost:4444/v1"

    def test_get_provider_config_case_insensitive_still_works(self):
        config = _make_config(openai_base_url="http://localhost:4444/v1")
        provider_config = config.providers.get_provider_config("OpenAI")
        assert provider_config.base_url == "http://localhost:4444/v1"


class TestEnvOverride:
    """Mirrors the WATSONX_ENDPOINT env-override test shape."""

    @pytest.fixture(autouse=True)
    def _isolated_config_file(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yaml"
            self.manager = ConfigManager(config_file=str(cfg_path))
            yield

    def _clear_openai_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    def test_env_override_sets_base_url(self, monkeypatch):
        self._clear_openai_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4444/v1")

        config = self.manager.load_config()

        assert config.providers.openai.base_url == "http://localhost:4444/v1"

    def test_no_env_var_leaves_base_url_empty(self, monkeypatch):
        self._clear_openai_env(monkeypatch)

        config = self.manager.load_config()

        assert config.providers.openai.base_url == ""

    def test_env_override_skipped_when_config_marked_edited(self, monkeypatch):
        """Matches the existing `edited` short-circuit for all env overrides."""
        self._clear_openai_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4444/v1")

        # Save an "edited" config with no base_url first.
        config = self.manager.load_config()
        config.edited = True
        config.providers.openai.base_url = ""
        self.manager.save_config_file(config, preserve_edited=True)
        self.manager.reload_config()

        reloaded = self.manager.get_config()
        assert reloaded.edited is True
        assert reloaded.providers.openai.base_url == ""

    def test_env_override_does_not_clobber_other_openai_fields(self, monkeypatch):
        self._clear_openai_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4444/v1")

        config = self.manager.load_config()

        assert config.providers.openai.api_key == "sk-from-env"
        assert config.providers.openai.base_url == "http://localhost:4444/v1"
