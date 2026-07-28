"""Tests for Docling restart keyed to OpenRAG version upgrades."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tui.managers.docling_manager import DoclingManager


@pytest.fixture
def docling_manager(tmp_path, monkeypatch):
    # Reset singleton so each test gets a fresh instance bound to tmp_path.
    DoclingManager._instance = None
    DoclingManager._initialized = False
    monkeypatch.setattr("utils.paths.get_tui_dir", lambda: Path(tmp_path))
    monkeypatch.setattr("tui.managers.docling_manager.OPENRAG_VERSION", "0.6.0")
    manager = DoclingManager()
    yield manager
    DoclingManager._instance = None
    DoclingManager._initialized = False


def test_stamp_matches_current_when_file_written(docling_manager):
    docling_manager._write_started_openrag_version()
    assert docling_manager._read_started_openrag_version() == "0.6.0"
    assert docling_manager.started_for_current_openrag_version() is True


def test_stamp_mismatch_when_missing_or_stale(docling_manager):
    assert docling_manager.started_for_current_openrag_version() is False
    docling_manager._openrag_version_file.write_text("0.5.1")
    assert docling_manager.started_for_current_openrag_version() is False


@pytest.mark.asyncio
async def test_start_restarts_when_openrag_version_mismatches(docling_manager, monkeypatch):
    docling_manager._openrag_version_file.write_text("0.5.1")
    stop = AsyncMock(return_value=(True, "stopped"))
    calls = {"n": 0}

    def _is_running():
        calls["n"] += 1
        # First check in start() → True (triggers upgrade stop)
        return calls["n"] == 1

    monkeypatch.setattr(docling_manager, "is_running", _is_running)
    monkeypatch.setattr(docling_manager, "stop", stop)

    # Avoid actually spawning uvx: fail early after stop by claiming port in use
    import socket

    class _Sock:
        def settimeout(self, *_a, **_k):
            return None

        def connect_ex(self, *_a, **_k):
            return 0

        def close(self):
            return None

    monkeypatch.setattr(socket, "socket", lambda *a, **k: _Sock())

    success, message = await docling_manager.start()
    stop.assert_awaited_once()
    assert success is False
    assert "already in use" in message.lower()


@pytest.mark.asyncio
async def test_ensure_running_returns_success_when_up_to_date(docling_manager, monkeypatch):
    docling_manager._write_started_openrag_version()
    monkeypatch.setattr(docling_manager, "is_running", lambda: True)
    start = AsyncMock()
    monkeypatch.setattr(docling_manager, "start", start)

    success, message = await docling_manager.ensure_running()
    assert success is True
    assert "already running" in message.lower()
    start.assert_not_awaited()
