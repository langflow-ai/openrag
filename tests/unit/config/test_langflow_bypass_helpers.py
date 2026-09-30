"""settings.is_*_with_langflow_disabled resolve env first, then config."""

from unittest.mock import patch

import pytest

from config.settings import (
    env_flag_enabled,
    is_chat_with_langflow_disabled,
    is_ingest_with_langflow_disabled,
)


class _Cfg:
    def __init__(self, chat: bool, ingest: bool):
        self.agent = type("A", (), {"disable_chat_with_langflow": chat})()
        self.knowledge = type("K", (), {"disable_ingest_with_langflow": ingest})()


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("1", True), ("yes", True), ("TRUE", True), ("false", False), ("", False)],
)
def test_env_flag_enabled_truthy_forms(monkeypatch, value, expected):
    monkeypatch.setenv("SOME_FLAG", value)
    assert env_flag_enabled("SOME_FLAG") is expected


def test_env_flag_enabled_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert env_flag_enabled("SOME_FLAG") is False


def test_env_var_wins_over_config_saying_off(monkeypatch):
    """Env is checked first, so a stale cached config cannot disarm the switch."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "true")
    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=False, ingest=False)):
        assert is_chat_with_langflow_disabled() is True
        assert is_ingest_with_langflow_disabled() is True


def test_falls_back_to_config_when_env_unset(monkeypatch):
    """With env unset the settings-UI value decides, both ways."""
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)

    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=True, ingest=True)):
        assert is_chat_with_langflow_disabled() is True
        assert is_ingest_with_langflow_disabled() is True

    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=False, ingest=False)):
        assert is_chat_with_langflow_disabled() is False
        assert is_ingest_with_langflow_disabled() is False
