"""Contract for the /nudges endpoints: the response shape the frontend splits on."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api import nudges


def _user():
    return SimpleNamespace(user_id="u1", db_user_id="db-u1", jwt_token="jwt")


@pytest.mark.asyncio
async def test_nudges_from_kb_endpoint_returns_response_string():
    chat_service = SimpleNamespace(nudges_chat=AsyncMock(return_value={"response": "A?\nB?\nC?"}))
    session_manager = object()

    result = await nudges.nudges_from_kb_endpoint(
        nudges.NudgesBody(filters={"data_sources": ["a.pdf"]}, limit=5),
        chat_service=chat_service,
        session_manager=session_manager,
        user=_user(),
    )

    assert result.status_code == 200
    assert json.loads(result.body) == {"response": "A?\nB?\nC?"}
    kwargs = chat_service.nudges_chat.await_args.kwargs
    assert kwargs["filters"] == {"data_sources": ["a.pdf"]}
    assert kwargs["limit"] == 5
    assert kwargs["storage_user_id"] == "db-u1"
    assert kwargs["session_manager"] is session_manager


@pytest.mark.asyncio
async def test_nudges_from_chat_id_endpoint_checks_ownership_and_passes_chat_id():
    chat_service = SimpleNamespace(nudges_chat=AsyncMock(return_value={"response": "Next?"}))

    with patch("api.chat._assert_owns", AsyncMock()) as assert_owns:
        result = await nudges.nudges_from_chat_id_endpoint(
            "chat-1",
            nudges.NudgesBody(),
            chat_service=chat_service,
            session_manager=object(),
            user=_user(),
        )

    assert json.loads(result.body) == {"response": "Next?"}
    assert_owns.assert_awaited_once_with("chat-1", "db-u1")
    assert chat_service.nudges_chat.await_args.kwargs["previous_response_id"] == "chat-1"
