from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


class _User:
    def __init__(self, uid):
        self.db_user_id = uid
        self.user_id = uid


def _fake_ownership(owners: dict[str, Any]) -> AsyncMock:
    svc = AsyncMock()
    svc.get_session_owner = AsyncMock(side_effect=lambda sid: owners.get(sid))

    return svc


@pytest.mark.asyncio
async def test_bulk_delete_authorized_ids_passed_to_service(monkeypatch):
    import json

    from api import chat as chat_module

    monkeypatch.setattr(
        "services.session_ownership_service.session_ownership_service",
        _fake_ownership({"a": "alice", "b": "bob"}),
    )
    fake_service = AsyncMock()
    fake_service.delete_sessions = AsyncMock(return_value={"deleted": ["a"], "failed": []})
    body = chat_module.BulkDeleteBody(session_ids=["a", "b"])

    resp = await chat_module.bulk_delete_sessions_endpoint(
        body=body,
        chat_service=fake_service,
        user=_User("alice"),  # type: ignore
    )

    payload = json.loads(resp.body)  # type: ignore
    fake_service.delete_sessions.assert_awaited_once_with("alice", ["a"])

    assert payload["deleted"] == ["a"]
    assert "b" in payload["failed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="session_ids", argvalues=[[], [str(i) for i in range(101)]])
async def test_bulk_delete_reject_cases(session_ids):
    from api import chat as chat_module

    body = chat_module.BulkDeleteBody(session_ids=session_ids)

    with pytest.raises(HTTPException) as exc:
        await chat_module.bulk_delete_sessions_endpoint(
            body=body,
            chat_service=AsyncMock(),
            user=_User("alice"),  # type: ignore
        )
    assert exc.value.status_code == 400
