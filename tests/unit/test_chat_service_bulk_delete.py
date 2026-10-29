from unittest.mock import AsyncMock

import pytest


def _make_service():
    from services.chat_service import ChatService

    return ChatService.__new__(ChatService)


def _patch_owner(monkeypatch, owners):
    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service.get_session_owner",
        AsyncMock(side_effect=lambda sid: owners.get(sid)),
    )


@pytest.mark.asyncio
async def test_bulk_delete_all_succeed(monkeypatch):
    svc = _make_service()
    _patch_owner(monkeypatch, {"a": "alice", "b": "alice"})
    svc.delete_session = AsyncMock(return_value={"success": True, "error": None})

    result = await svc.delete_sessions("alice", ["a", "b"])

    assert result == {"deleted": ["a", "b"], "failed": []}


@pytest.mark.asyncio
async def test_bulk_delete_dedupes(monkeypatch):
    svc = _make_service()
    _patch_owner(monkeypatch, {"a": "alice"})
    svc.delete_session = AsyncMock(return_value={"success": True, "error": None})

    result = await svc.delete_sessions("alice", ["a", "a", "a"])

    assert result == {"deleted": ["a"], "failed": []}
    assert svc.delete_session.await_count == 1  # deleted at most once


@pytest.mark.asyncio
async def test_bulk_delete_reports_delete_failure(monkeypatch):
    svc = _make_service()
    _patch_owner(monkeypatch, {"x": "alice"})
    svc.delete_session = AsyncMock(return_value={"success": False, "error": "nope"})

    result = await svc.delete_sessions("alice", ["x"])

    assert result == {"deleted": [], "failed": ["x"]}


@pytest.mark.asyncio
async def test_bulk_delete_never_raises_on_error(monkeypatch):
    svc = _make_service()
    _patch_owner(monkeypatch, {"x": "alice"})
    svc.delete_session = AsyncMock(side_effect=RuntimeError("boom"))

    result = await svc.delete_sessions("alice", ["x"])

    assert result == {"deleted": [], "failed": ["x"]}
