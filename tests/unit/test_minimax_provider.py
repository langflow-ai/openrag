"""Unit tests for MiniMax provider integration.

Tests verify that MiniMax provider configuration, model constants,
and validation dispatch are correctly integrated.
"""

import os
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import asdict

import pytest


class TestMiniMaxConfig:
    """Tests for MiniMax configuration dataclass."""

    def test_minimax_config_defaults(self):
        """MiniMaxConfig should have empty defaults."""
        from config.config_manager import MiniMaxConfig

        config = MiniMaxConfig()
        assert config.api_key == ""
        assert config.configured is False

    def test_minimax_config_with_values(self):
        """MiniMaxConfig should accept custom values."""
        from config.config_manager import MiniMaxConfig

        config = MiniMaxConfig(api_key="test-key", configured=True)
        assert config.api_key == "test-key"
        assert config.configured is True

    def test_providers_config_has_minimax(self):
        """ProvidersConfig should include minimax field."""
        from config.config_manager import (
            ProvidersConfig,
            OpenAIConfig,
            AnthropicConfig,
            WatsonXConfig,
            OllamaConfig,
            MiniMaxConfig,
        )

        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            minimax=MiniMaxConfig(),
        )
        assert hasattr(providers, "minimax")
        assert isinstance(providers.minimax, MiniMaxConfig)

    def test_get_provider_config_minimax(self):
        """get_provider_config should return MiniMax config for 'minimax'."""
        from config.config_manager import (
            ProvidersConfig,
            OpenAIConfig,
            AnthropicConfig,
            WatsonXConfig,
            OllamaConfig,
            MiniMaxConfig,
        )

        minimax_config = MiniMaxConfig(api_key="mm-key", configured=True)
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            minimax=minimax_config,
        )
        result = providers.get_provider_config("minimax")
        assert result.api_key == "mm-key"
        assert result.configured is True

    def test_get_provider_config_minimax_case_insensitive(self):
        """get_provider_config should handle 'MiniMax' case-insensitively."""
        from config.config_manager import (
            ProvidersConfig,
            OpenAIConfig,
            AnthropicConfig,
            WatsonXConfig,
            OllamaConfig,
            MiniMaxConfig,
        )

        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            minimax=MiniMaxConfig(api_key="test"),
        )
        result = providers.get_provider_config("MINIMAX")
        assert result.api_key == "test"


class TestMiniMaxModelConstants:
    """Tests for MiniMax model constants."""

    def test_validation_models_exist(self):
        """MINIMAX_VALIDATION_MODELS should contain expected models."""
        from config.model_constants import MINIMAX_VALIDATION_MODELS

        assert "MiniMax-M2.7" in MINIMAX_VALIDATION_MODELS
        assert "MiniMax-M2.7-highspeed" in MINIMAX_VALIDATION_MODELS
        assert "MiniMax-M2.5" in MINIMAX_VALIDATION_MODELS
        assert "MiniMax-M2.5-highspeed" in MINIMAX_VALIDATION_MODELS
        assert len(MINIMAX_VALIDATION_MODELS) == 4

    def test_m27_models_first(self):
        """M2.7 models should appear before M2.5 models in the list."""
        from config.model_constants import MINIMAX_VALIDATION_MODELS

        m27_idx = MINIMAX_VALIDATION_MODELS.index("MiniMax-M2.7")
        m25_idx = MINIMAX_VALIDATION_MODELS.index("MiniMax-M2.5")
        assert m27_idx < m25_idx

    def test_default_model(self):
        """MINIMAX_DEFAULT_LANGUAGE_MODEL should be MiniMax-M2.7."""
        from config.model_constants import MINIMAX_DEFAULT_LANGUAGE_MODEL

        assert MINIMAX_DEFAULT_LANGUAGE_MODEL == "MiniMax-M2.7"


class TestMiniMaxOpenRAGConfig:
    """Tests for MiniMax in OpenRAGConfig."""

    def test_from_dict_with_minimax(self):
        """OpenRAGConfig.from_dict should handle minimax provider data."""
        from config.config_manager import OpenRAGConfig

        data = {
            "providers": {
                "openai": {},
                "anthropic": {},
                "watsonx": {},
                "ollama": {},
                "minimax": {"api_key": "test-mm-key", "configured": True},
            },
            "knowledge": {},
            "agent": {},
            "onboarding": {},
        }

        config = OpenRAGConfig.from_dict(data)
        assert config.providers.minimax.api_key == "test-mm-key"
        assert config.providers.minimax.configured is True

    def test_from_dict_without_minimax(self):
        """OpenRAGConfig.from_dict should use defaults when minimax is missing."""
        from config.config_manager import OpenRAGConfig

        data = {
            "providers": {
                "openai": {},
                "anthropic": {},
                "watsonx": {},
                "ollama": {},
            },
            "knowledge": {},
            "agent": {},
            "onboarding": {},
        }

        config = OpenRAGConfig.from_dict(data)
        assert config.providers.minimax.api_key == ""
        assert config.providers.minimax.configured is False

    def test_to_dict_includes_minimax(self):
        """Config serialization should include minimax."""
        from config.config_manager import OpenRAGConfig

        data = {
            "providers": {
                "openai": {},
                "anthropic": {},
                "watsonx": {},
                "ollama": {},
                "minimax": {"api_key": "key123"},
            },
            "knowledge": {},
            "agent": {},
            "onboarding": {},
        }

        config = OpenRAGConfig.from_dict(data)
        d = config.to_dict()
        assert "minimax" in d["providers"]
        assert d["providers"]["minimax"]["api_key"] == "key123"


class TestMiniMaxEnvOverrides:
    """Tests for MiniMax environment variable loading."""

    def test_minimax_api_key_env_override(self):
        """MINIMAX_API_KEY env var should override config."""
        from config.config_manager import ConfigManager

        with patch.dict(os.environ, {"MINIMAX_API_KEY": "env-mm-key"}, clear=False):
            manager = ConfigManager(config_file="/nonexistent/path.yaml")
            config = manager.load_config()
            assert config.providers.minimax.api_key == "env-mm-key"
