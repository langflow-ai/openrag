from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


class _User:
    def __init__(self, uid):
        self.db_user_id = uid
        self.user_id = uid


@pytest.mark.asyncio
async def test_bulk_delete_forwards_ids_and_maps_response():
    import json

    from api import chat as chat_module

    fake_service = AsyncMock()
    fake_service.delete_sessions = AsyncMock(return_value={"deleted": ["a"], "failed": ["b"]})
    body = chat_module.BulkDeleteBody(session_ids=["a", "b"])

    resp = await chat_module.bulk_delete_sessions_endpoint(
        body=body,
        chat_service=fake_service,
        user=_User("alice"),
    )

    payload = json.loads(resp.body)
    fake_service.delete_sessions.assert_awaited_once_with("alice", ["a", "b"])
    assert payload == {"deleted": ["a"], "failed": ["b"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(argnames="session_ids", argvalues=[[], [str(i) for i in range(101)]])
async def test_bulk_delete_reject_cases(session_ids):
    from api import chat as chat_module

    body = chat_module.BulkDeleteBody(session_ids=session_ids)

    with pytest.raises(HTTPException) as exc:
        await chat_module.bulk_delete_sessions_endpoint(
            body=body,
            chat_service=AsyncMock(),
            user=_User("alice"),
        )
    assert exc.value.status_code == 400
