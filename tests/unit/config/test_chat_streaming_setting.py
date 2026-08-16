"""Unit tests for the chat_streaming configuration setting.

Deployments that hide the chat page's toggles need the streaming mode settable
from configuration, since turning streaming off is the only way to work around a
model that streams unreliably.
"""

import tempfile
from pathlib import Path

from config.config_manager import ConfigManager


def test_chat_streaming_defaults_on(monkeypatch):
    monkeypatch.delenv("CHAT_STREAMING_ENABLED", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        cm = ConfigManager(config_file=str(Path(tmp) / "config.yaml"))
        assert cm.load_config().agent.chat_streaming is True


def test_chat_streaming_env_override(monkeypatch):
    for value, expected in (("false", False), ("true", True), ("1", True), ("no", False)):
        monkeypatch.setenv("CHAT_STREAMING_ENABLED", value)
        with tempfile.TemporaryDirectory() as tmp:
            cm = ConfigManager(config_file=str(Path(tmp) / "config.yaml"))
            assert cm.load_config().agent.chat_streaming is expected, value


def test_chat_streaming_preserves_on_save(monkeypatch):
    """Once edited, the persisted value wins over the env var."""
    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        config = cm.load_config()

        config.agent.chat_streaming = False
        config.edited = True
        cm.save_config_file(config)

        reloaded = ConfigManager(config_file=str(cfg_file)).load_config()
        assert reloaded.agent.chat_streaming is False


def test_chat_streaming_round_trips_through_settings_models():
    from api.settings.models import AgentConfig, SettingsUpdateBody

    assert SettingsUpdateBody(chat_streaming=False).chat_streaming is False
    # Omitted stays None so update_settings leaves the stored value alone.
    assert SettingsUpdateBody().chat_streaming is None

    section = AgentConfig(
        llm_model="gpt-4.1-nano",
        llm_provider="azure_ai_foundry",
        disable_chat_with_langflow=True,
        chat_streaming=False,
        system_prompt="",
    )
    assert section.chat_streaming is False
