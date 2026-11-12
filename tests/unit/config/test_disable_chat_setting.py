"""Unit tests for the environment-only native chat deployment setting."""

from unittest.mock import patch

import pytest

from config.settings import is_chat_with_langflow_disabled


def test_disable_chat_default(monkeypatch):
    """Langflow remains the default when the deployment variable is unset."""
    monkeypatch.delenv("DISABLE_CHAT_WITH_LANGFLOW", raising=False)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    assert is_chat_with_langflow_disabled() is False


@pytest.mark.parametrize(
    ("value", "expected"),
    (("true", True), ("1", True), ("yes", True), ("false", False)),
)
def test_disable_chat_env_override(monkeypatch, value, expected):
    """Truthy values enable the built-in agent without changing config data."""
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", value)
    assert is_chat_with_langflow_disabled() is expected


def test_disable_chat_env_is_unavailable_without_database_storage(monkeypatch):
    """Native history has no JSON or hybrid fallback."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    assert is_chat_with_langflow_disabled() is False


def test_disable_chat_ignores_legacy_persisted_value(monkeypatch):
    """A previous UI value cannot override the deployment environment."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "false")
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    config = type(
        "Config",
        (),
        {"agent": type("Agent", (), {"disable_chat_with_langflow": True})()},
    )()
    with patch("config.settings.get_openrag_config", return_value=config):
        assert is_chat_with_langflow_disabled() is False
