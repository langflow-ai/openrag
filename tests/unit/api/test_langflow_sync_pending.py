"""Tests for deferred Langflow settings reconciliation."""

from unittest.mock import AsyncMock, Mock

import pytest

from api.settings import langflow_sync
from config.config_manager import OpenRAGConfig


@pytest.mark.asyncio
async def test_pending_sync_clears_marker_only_after_success(monkeypatch):
    config = OpenRAGConfig.from_dict({"langflow_sync_pending": True})
    reapply = AsyncMock(return_value=True)
    save = Mock(return_value=True)

    monkeypatch.setattr(langflow_sync, "get_openrag_config", lambda: config)
    monkeypatch.setattr(langflow_sync.settings, "is_langflow_disabled", lambda _config: False)
    monkeypatch.setattr(langflow_sync, "reapply_all_settings", reapply)
    monkeypatch.setattr(langflow_sync.config_manager, "save_config_file", save)

    assert await langflow_sync.sync_pending_langflow_settings() is True
    assert config.langflow_sync_pending is False
    reapply.assert_awaited_once()
    save.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_failed_pending_sync_keeps_marker_for_startup_retry(monkeypatch):
    config = OpenRAGConfig.from_dict({"langflow_sync_pending": True})
    reapply = AsyncMock(return_value=False)

    monkeypatch.setattr(langflow_sync, "get_openrag_config", lambda: config)
    monkeypatch.setattr(langflow_sync.settings, "is_langflow_disabled", lambda _config: False)
    monkeypatch.setattr(langflow_sync, "reapply_all_settings", reapply)

    assert await langflow_sync.sync_pending_langflow_settings() is False
    assert config.langflow_sync_pending is True
    reapply.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_sync_does_not_clear_a_newer_config(monkeypatch):
    stale = OpenRAGConfig.from_dict({"langflow_sync_pending": True})
    newer = OpenRAGConfig.from_dict(
        {"langflow_sync_pending": True, "agent": {"system_prompt": "new"}}
    )
    configs = iter([stale, newer, newer, newer])

    monkeypatch.setattr(langflow_sync, "get_openrag_config", lambda: next(configs))
    monkeypatch.setattr(langflow_sync.settings, "is_langflow_disabled", lambda _config: False)
    monkeypatch.setattr(langflow_sync, "reapply_all_settings", AsyncMock(return_value=True))
    save = Mock()
    monkeypatch.setattr(langflow_sync.config_manager, "save_config_file", save)

    assert await langflow_sync.sync_pending_langflow_settings() is True
    assert newer.langflow_sync_pending is False
    save.assert_called_once_with(newer)
