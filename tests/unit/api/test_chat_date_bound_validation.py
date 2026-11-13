"""Chat endpoints reject malformed date bounds before they reach retrieval."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api import chat as chat_api
from api.v1 import chat as v1_chat

BAD_FILTERS = [
    {"created_after": "not-a-date"},
    {"created_before": ["2026-10-10T00:00:00Z"]},
    {"created_after": "2026-10-10T00:00:00Z", "created_before": "2026-10-07T00:00:00Z"},
]


@pytest.fixture
def user():
    return SimpleNamespace(user_id="u1", jwt_token="jwt")


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", BAD_FILTERS)
async def test_chat_endpoint_rejects_invalid_date_bounds(monkeypatch, user, filters):
    monkeypatch.setattr(chat_api, "_assert_owns", AsyncMock())
    chat_service = SimpleNamespace(chat=AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_endpoint(
            chat_api.ChatBody(prompt="hi", filters=filters), chat_service, None, user
        )

    assert exc.value.status_code == 422
    chat_service.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_endpoint_accepts_valid_date_bounds(monkeypatch, user):
    monkeypatch.setattr(chat_api, "_assert_owns", AsyncMock())
    chat_service = SimpleNamespace(chat=AsyncMock(return_value={"response": "ok"}))

    await chat_api.chat_endpoint(
        chat_api.ChatBody(
            prompt="hi",
            filters={
                "created_after": "2026-10-07T00:00:00Z",
                "created_before": "2026-10-10T23:59:59Z",
            },
        ),
        chat_service,
        None,
        user,
    )

    chat_service.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_endpoint_rejects_native_chat_without_database_storage(monkeypatch, user):
    """The native endpoint is unavailable, while the rest of the app can start."""
    monkeypatch.setattr(chat_api, "get_storage_mode", lambda: "files")
    chat_service = SimpleNamespace(chat=AsyncMock())

    response = await chat_api.chat_endpoint(
        chat_api.ChatBody(prompt="hi"), chat_service, None, user
    )

    assert response.status_code == 503
    assert response.body == b'{"error":"Chat is temporarily unavailable. Please try again later."}'
    chat_service.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_langflow_endpoint_reports_native_storage_error_when_switch_is_enabled(
    monkeypatch, user
):
    monkeypatch.setattr(chat_api, "DISABLE_CHAT_WITH_LANGFLOW", True)
    monkeypatch.setattr(chat_api, "get_storage_mode", lambda: "files")
    chat_service = SimpleNamespace(langflow_chat=AsyncMock())

    response = await chat_api.langflow_endpoint(
        chat_api.ChatBody(prompt="hi"), chat_service, None, user
    )

    assert response.status_code == 503
    chat_service.langflow_chat.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", BAD_FILTERS)
async def test_v1_chat_rejects_invalid_date_bounds(user, filters):
    chat_service = SimpleNamespace(chat=AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await v1_chat.chat_create_endpoint(
            v1_chat.ChatV1Body(message="hi", filters=filters),
            SimpleNamespace(headers={}),
            chat_service=chat_service,
            session_manager=None,
            user=user,
            knowledge_filter_service=None,
        )

    assert exc.value.status_code == 422
    chat_service.chat.assert_not_awaited()
