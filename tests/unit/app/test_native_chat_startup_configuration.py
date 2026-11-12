"""Startup validation for the environment-only native chat switch."""

import pytest

from app.container import _validate_native_chat_storage_mode


def test_native_chat_startup_allows_database_storage(monkeypatch):
    """Native chat starts normally when its durable history store is enabled."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")

    _validate_native_chat_storage_mode()


def test_native_chat_startup_rejects_non_database_storage(monkeypatch):
    """Fail before serving requests when native history would be unavailable."""
    monkeypatch.setenv("DISABLE_CHAT_WITH_LANGFLOW", "true")
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")

    with pytest.raises(RuntimeError, match="OPENRAG_STORAGE_MODE=db"):
        _validate_native_chat_storage_mode()
