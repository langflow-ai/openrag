"""Settings helpers for Langflow bypass environment variables."""

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


def test_env_var_enables_chat_bypass(monkeypatch):
    """The native chat choice is controlled by its deployment variable."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "true")
    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=False, ingest=False)):
        assert is_chat_with_langflow_disabled() is True
        assert is_ingest_with_langflow_disabled() is True


def test_chat_bypass_does_not_fall_back_to_persisted_config(monkeypatch):
    """A legacy persisted value cannot change the environment-only choice."""
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    monkeypatch.delenv("DISABLE_INGEST_WITH_LANGFLOW", raising=False)

    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=True, ingest=True)):
        assert is_chat_with_langflow_disabled() is False
        assert is_ingest_with_langflow_disabled() is True

    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=False, ingest=False)):
        assert is_chat_with_langflow_disabled() is False
        assert is_ingest_with_langflow_disabled() is False


def test_chat_bypass_is_unavailable_outside_database_mode(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    with patch("config.settings.get_openrag_config", return_value=_Cfg(chat=True, ingest=False)):
        assert is_chat_with_langflow_disabled() is False
