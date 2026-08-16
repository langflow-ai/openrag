"""Unit tests for the disable_chat_with_langflow configuration setting.

Mirrors test_disable_ingest_setting.py — the chat-side flag exists so a
deployment running without Langflow gets a chat UI that posts to the
langflowless /chat endpoint instead of /langflow.
"""

import tempfile
from pathlib import Path

from config.config_manager import ConfigManager


def test_disable_chat_default(monkeypatch):
    """Defaults to False so Langflow stays the out-of-box chat path."""
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.agent.disable_chat_with_langflow is False


def test_disable_chat_env_override(monkeypatch):
    """DISABLE_CHAT_WITH_LANGFLOW sets the value, accepting the usual truthy forms."""
    for value, expected in (("true", True), ("1", True), ("yes", True), ("false", False)):
        monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", value)
        with tempfile.TemporaryDirectory() as tmp:
            cfg_file = Path(tmp) / "config.yaml"
            cm = ConfigManager(config_file=str(cfg_file))
            config = cm.load_config()
            assert config.agent.disable_chat_with_langflow is expected, value


def test_disable_chat_preserves_on_save(monkeypatch):
    """Once edited, the persisted value wins over the env var on later loads."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()
        assert config.agent.disable_chat_with_langflow is False

        config.agent.disable_chat_with_langflow = True
        config.edited = True
        cm.save_config_file(config)

        cm2 = ConfigManager(config_file=str(cfg_file))
        config2 = cm2.load_config()
        assert config2.agent.disable_chat_with_langflow is True

        monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "false")
        config3 = cm2.load_config()
        assert config3.agent.disable_chat_with_langflow is True


def test_disable_chat_round_trips_through_settings_models():
    """The flag survives the request model and reaches the response model."""
    from api.settings.models import AgentConfig, SettingsUpdateBody

    body = SettingsUpdateBody(disable_chat_with_langflow=True)
    assert body.disable_chat_with_langflow is True

    # Omitted stays None so update_settings leaves the stored value alone.
    assert SettingsUpdateBody().disable_chat_with_langflow is None

    response_section = AgentConfig(
        llm_model="Phi-4-mini-instruct",
        llm_provider="azure_ai_foundry",
        disable_chat_with_langflow=True,
        chat_streaming=True,
        system_prompt="",
    )
    assert response_section.disable_chat_with_langflow is True
