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
async def test_bulk_delete_mixed_ownership(monkeypatch):
    svc = _make_service()
    # alice owns s1; s2 is bob's; s3 has no owner
    _patch_owner(monkeypatch, {"s1": "alice", "s2": "bob", "s3": None})
    svc.delete_session = AsyncMock(return_value={"success": True, "error": None})

    result = await svc.delete_sessions("alice", ["s1", "s2", "s3"])

    assert result["deleted"] == ["s1"]
    assert sorted(result["failed"]) == ["s2", "s3"]
    # only the owned id ever reaches delete_session
    called = {c.args[1] for c in svc.delete_session.call_args_list}
    assert called == {"s1"}


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
