"""Tests for default model selection when a provider is removed.

When a provider is removed and it was the active LLM or embedding provider,
the backend should fall back to another configured provider AND select a
sensible default model (not an empty string).
"""

from api.settings.helpers import (
    _default_embedding_model,
    _default_llm_model,
    _first_configured_embedding_provider,
    _first_configured_llm_provider,
)
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
from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
from config.model_constants import (
    ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
    OPENAI_DEFAULT_LANGUAGE_MODEL,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(
    *,
    openai=False,
    anthropic=False,
    ollama=False,
    watsonx=False,
    llm_provider="openai",
    llm_model="gpt-5.4-mini",
    embedding_provider="openai",
    embedding_model="text-embedding-3-small",
) -> OpenRAGConfig:
    """Build a minimal OpenRAGConfig with the requested providers configured."""
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(api_key="sk-test" if openai else "", configured=openai),
            anthropic=AnthropicConfig(api_key="sk-ant" if anthropic else "", configured=anthropic),
            ollama=OllamaConfig(
                endpoint="http://localhost:11434" if ollama else "", configured=ollama
            ),
            watsonx=WatsonXConfig(
                api_key="wx-key" if watsonx else "",
                endpoint="https://us-south.ml.cloud.ibm.com" if watsonx else "",
                project_id="pid" if watsonx else "",
                configured=watsonx,
            ),
        ),
        knowledge=KnowledgeConfig(
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
        ),
        agent=AgentConfig(
            llm_model=llm_model,
            llm_provider=llm_provider,
        ),
        onboarding=OnboardingState(),
        edited=True,
    )


# ---------------------------------------------------------------------------
# _default_llm_model
# ---------------------------------------------------------------------------


class TestDefaultLlmModel:
    def test_openai_returns_static_default(self):
        assert _default_llm_model("openai") == OPENAI_DEFAULT_LANGUAGE_MODEL

    def test_anthropic_returns_static_default(self):
        assert _default_llm_model("anthropic") == ANTHROPIC_DEFAULT_LANGUAGE_MODEL

    def test_ollama_returns_empty(self):
        assert _default_llm_model("ollama") == ""

    def test_watsonx_returns_empty(self):
        assert _default_llm_model("watsonx") == ""

    def test_unknown_provider_returns_empty(self):
        assert _default_llm_model("nonexistent") == ""


# ---------------------------------------------------------------------------
# _default_embedding_model
# ---------------------------------------------------------------------------


class TestDefaultEmbeddingModel:
    def test_openai_returns_static_default(self):
        assert _default_embedding_model("openai") == OPENAI_DEFAULT_EMBEDDING_MODEL

    def test_ollama_returns_empty(self):
        assert _default_embedding_model("ollama") == ""

    def test_watsonx_returns_empty(self):
        assert _default_embedding_model("watsonx") == ""

    def test_unknown_provider_returns_empty(self):
        assert _default_embedding_model("nonexistent") == ""


# ---------------------------------------------------------------------------
# _first_configured_llm_provider
# ---------------------------------------------------------------------------


class TestFirstConfiguredLlmProvider:
    def test_excludes_removed_provider(self):
        config = _make_config(openai=True, anthropic=True)
        assert _first_configured_llm_provider(config, "openai") == "anthropic"

    def test_respects_priority_order(self):
        """Order is openai > anthropic > watsonx > ollama."""
        config = _make_config(openai=True, anthropic=True, watsonx=True, ollama=True)
        assert _first_configured_llm_provider(config, "openai") == "anthropic"
        assert _first_configured_llm_provider(config, "anthropic") == "openai"

    def test_skips_unconfigured(self):
        config = _make_config(ollama=True)
        assert _first_configured_llm_provider(config, "openai") == "ollama"

    def test_falls_back_to_openai_when_none_configured(self):
        config = _make_config()
        assert _first_configured_llm_provider(config, "anthropic") == "openai"


# ---------------------------------------------------------------------------
# _first_configured_embedding_provider
# ---------------------------------------------------------------------------


class TestFirstConfiguredEmbeddingProvider:
    def test_excludes_removed_provider(self):
        config = _make_config(openai=True, ollama=True)
        assert _first_configured_embedding_provider(config, "openai") == "ollama"

    def test_anthropic_never_returned(self):
        """Anthropic has no embedding models; it must never be a fallback."""
        config = _make_config(anthropic=True, ollama=True)
        assert _first_configured_embedding_provider(config, "openai") == "ollama"

    def test_respects_priority_order(self):
        """Order is openai > watsonx > ollama."""
        config = _make_config(openai=True, watsonx=True, ollama=True)
        assert _first_configured_embedding_provider(config, "openai") == "watsonx"

    def test_returns_empty_when_none_configured(self):
        config = _make_config()
        assert _first_configured_embedding_provider(config, "ollama") == ""


# ---------------------------------------------------------------------------
# Simulated provider removal: LLM model default
# ---------------------------------------------------------------------------


class TestProviderRemovalLlmDefault:
    """Simulate the provider-removal code path from endpoints.py and verify
    that the resulting llm_model is a sensible default, not empty."""

    def _simulate_llm_removal(self, config: OpenRAGConfig, removed: str):
        """Replicate the fallback logic from update_settings()."""
        if config.agent.llm_provider == removed:
            fb = _first_configured_llm_provider(config, removed)
            config.agent.llm_provider = fb
            config.agent.llm_model = _default_llm_model(fb)

    def test_remove_anthropic_falls_back_to_openai_model(self):
        config = _make_config(
            openai=True,
            anthropic=True,
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-6",
        )
        self._simulate_llm_removal(config, "anthropic")
        assert config.agent.llm_provider == "openai"
        assert config.agent.llm_model == OPENAI_DEFAULT_LANGUAGE_MODEL

    def test_remove_openai_falls_back_to_anthropic_model(self):
        config = _make_config(
            openai=True,
            anthropic=True,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
        )
        self._simulate_llm_removal(config, "openai")
        assert config.agent.llm_provider == "anthropic"
        assert config.agent.llm_model == ANTHROPIC_DEFAULT_LANGUAGE_MODEL

    def test_remove_openai_falls_back_to_ollama_empty_model(self):
        """Ollama models are dynamic — backend returns empty, frontend picks."""
        config = _make_config(
            openai=True,
            ollama=True,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
        )
        self._simulate_llm_removal(config, "openai")
        assert config.agent.llm_provider == "ollama"
        assert config.agent.llm_model == ""

    def test_remove_watsonx_falls_back_to_openai_model(self):
        config = _make_config(
            openai=True,
            watsonx=True,
            llm_provider="watsonx",
            llm_model="ibm/granite-13b-chat-v2",
        )
        self._simulate_llm_removal(config, "watsonx")
        assert config.agent.llm_provider == "openai"
        assert config.agent.llm_model == OPENAI_DEFAULT_LANGUAGE_MODEL

    def test_no_change_if_different_provider_removed(self):
        """If the removed provider wasn't the active one, nothing changes."""
        config = _make_config(
            openai=True,
            anthropic=True,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
        )
        self._simulate_llm_removal(config, "anthropic")
        assert config.agent.llm_provider == "openai"
        assert config.agent.llm_model == "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Simulated provider removal: embedding model default
# ---------------------------------------------------------------------------


class TestProviderRemovalEmbeddingDefault:
    """Simulate embedding provider fallback on removal."""

    def _simulate_embedding_removal(self, config: OpenRAGConfig, removed: str):
        if config.knowledge.embedding_provider == removed:
            fb = _first_configured_embedding_provider(config, removed)
            config.knowledge.embedding_provider = fb
            config.knowledge.embedding_model = _default_embedding_model(fb)

    def test_remove_ollama_falls_back_to_openai_embedding(self):
        config = _make_config(
            openai=True,
            ollama=True,
            embedding_provider="ollama",
            embedding_model="nomic-embed-text",
        )
        self._simulate_embedding_removal(config, "ollama")
        assert config.knowledge.embedding_provider == "openai"
        assert config.knowledge.embedding_model == OPENAI_DEFAULT_EMBEDDING_MODEL

    def test_remove_openai_falls_back_to_watsonx_empty_embedding(self):
        config = _make_config(
            openai=True,
            watsonx=True,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        )
        self._simulate_embedding_removal(config, "openai")
        assert config.knowledge.embedding_provider == "watsonx"
        assert config.knowledge.embedding_model == ""

    def test_remove_watsonx_falls_back_to_openai_embedding(self):
        config = _make_config(
            openai=True,
            watsonx=True,
            embedding_provider="watsonx",
            embedding_model="ibm/slate-125m-english-rtrvr",
        )
        self._simulate_embedding_removal(config, "watsonx")
        assert config.knowledge.embedding_provider == "openai"
        assert config.knowledge.embedding_model == OPENAI_DEFAULT_EMBEDDING_MODEL

    def test_no_change_if_different_provider_removed(self):
        config = _make_config(
            openai=True,
            ollama=True,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        )
        self._simulate_embedding_removal(config, "ollama")
        assert config.knowledge.embedding_provider == "openai"
        assert config.knowledge.embedding_model == "text-embedding-3-small"
