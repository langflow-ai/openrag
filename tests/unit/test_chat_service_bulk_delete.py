from unittest.mock import AsyncMock

import pytest


def _make_service():
    from services.chat_service import ChatService

    return ChatService.__new__(ChatService)


@pytest.mark.asyncio
async def test_bulk_delete_mixed_outcomes():
    svc = _make_service()

    async def fake_delete(user_id, session_id):
        if session_id == "s2":
            return {"success": False, "error": "Conversation not found"}
        return {"success": True, "error": None}

    svc.delete_session = AsyncMock(side_effect=fake_delete)

    result = await svc.delete_sessions("alice", ["s1", "s2"])

    assert result["deleted"] == ["s1"]
    assert result["failed"] == ["s2"]


@pytest.mark.asyncio
async def test_bulk_delete_all_succeed():
    svc = _make_service()
    svc.delete_session = AsyncMock(return_value={"success": True, "error": None})

    result = await svc.delete_sessions("alice", ["a", "b"])

    assert result == {"deleted": ["a", "b"], "failed": []}


@pytest.mark.asyncio
async def test_bulk_delete_never_raises_on_error():
    svc = _make_service()
    svc.delete_session = AsyncMock(side_effect=RuntimeError("boom"))

    result = await svc.delete_sessions("alice", ["x"])

    assert result == {"deleted": [], "failed": ["x"]}
