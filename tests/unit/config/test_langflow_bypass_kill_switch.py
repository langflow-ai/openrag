"""The Langflow bypass env vars must survive an `edited` config.

config_manager skips *all* env overrides once config.yaml is marked edited
(i.e. once anyone has saved settings in the UI). That is fine for ordinary
settings, but it silently disarms DISABLE_INGEST_WITH_LANGFLOW /
DISABLE_CHAT_WITH_LANGFLOW, which operators set precisely to keep a
deployment off Langflow. These flags are therefore applied on-only, before
the edited check: `true` forces the bypass, `false`/unset defers to the
saved config so the UI toggle still turns it back off.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from config.config_manager import ConfigManager

EDITED_CONFIG_OFF = {
    "edited": True,
    "knowledge": {"disable_ingest_with_langflow": False},
    "agent": {"disable_chat_with_langflow": False},
}


def _load(tmp: str, file_config: dict) -> "object":
    cfg_file = Path(tmp) / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(file_config))
    return ConfigManager(config_file=str(cfg_file)).load_config()


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", " True "])
def test_env_forces_bypass_on_edited_config(monkeypatch, value):
    """A truthy env var wins over an edited config that says False."""
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", value)
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", value)
    with tempfile.TemporaryDirectory() as tmp:
        config = _load(tmp, EDITED_CONFIG_OFF)
        assert config.edited is True
        assert config.knowledge.disable_ingest_with_langflow is True, value
        assert config.agent.disable_chat_with_langflow is True, value


def test_env_false_does_not_force_bypass_off(monkeypatch):
    """`false` must not override a UI toggle that turned the bypass on.

    .env.example ships both vars as `false`, so a forcing-off override would
    make the settings toggle impossible to keep enabled.
    """
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "false")
    with tempfile.TemporaryDirectory() as tmp:
        config = _load(
            tmp,
            {
                "edited": True,
                "knowledge": {"disable_ingest_with_langflow": True},
                "agent": {"disable_chat_with_langflow": True},
            },
        )
        assert config.knowledge.disable_ingest_with_langflow is True
        assert config.agent.disable_chat_with_langflow is True


def test_unset_env_leaves_edited_config_alone(monkeypatch):
    """With no env vars, an edited config is the sole source of truth."""
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        config = _load(tmp, EDITED_CONFIG_OFF)
        assert config.knowledge.disable_ingest_with_langflow is False
        assert config.agent.disable_chat_with_langflow is False
