"""Langflow bypass environment values survive an edited configuration.

The ingestion flag still modifies its persisted setting. Native chat remains
environment-only, so its variable is validated but never written to config.
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
        assert config.agent.disable_chat_with_langflow is False, value


def test_chat_env_false_leaves_legacy_config_unchanged(monkeypatch):
    """Legacy config remains readable, but no longer controls chat routing."""
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
