"""Startup validation for the environment-only native chat switch."""

import pytest

import app.container as container


def test_native_chat_startup_allows_database_storage(monkeypatch):
    """Native chat starts normally when its durable history store is enabled."""
    monkeypatch.setattr(container, "DISABLE_CHAT_WITH_LANGFLOW", True)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)

    container._validate_native_chat_storage_mode()


def test_native_chat_startup_rejects_non_database_storage(monkeypatch):
    """Fail before serving requests when native history would be unavailable."""
    monkeypatch.setattr(container, "DISABLE_CHAT_WITH_LANGFLOW", True)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")

    with pytest.raises(RuntimeError, match="OPENRAG_STORAGE_MODE=db"):
        container._validate_native_chat_storage_mode()
