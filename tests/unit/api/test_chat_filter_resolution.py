"""Chat endpoints scope retrieval with the saved filter named by `filter_id`.

The browser holds a copy of the filter taken when it was picked, so a later
edit on the Knowledge page must still reach the next chat turn, with Langflow
on or off.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api import chat as chat_api
from auth_context import (
    get_score_threshold,
    get_search_filters,
    get_search_limit,
    set_score_threshold,
    set_search_filters,
    set_search_limit,
)


@pytest.fixture
def user():
    return SimpleNamespace(user_id="u1", jwt_token="jwt", name="User", email="user@example.test")


@pytest.fixture(autouse=True)
def reset_search_context(monkeypatch):
    monkeypatch.setattr(chat_api, "_assert_owns", AsyncMock())
    monkeypatch.setattr(chat_api, "db_writes_enabled", lambda: True)
    set_search_filters(None)
    set_search_limit(10)
    set_score_threshold(0)
    yield
    set_search_filters(None)
    set_search_limit(10)
    set_score_threshold(0)


def _filter_service(filters, limit=5, score_threshold=0.4):
    query_data = {
        "query": "",
        "filters": filters,
        "limit": limit,
        "scoreThreshold": score_threshold,
    }
    return SimpleNamespace(
        get_knowledge_filter=AsyncMock(
            return_value={"success": True, "filter": {"query_data": json.dumps(query_data)}}
        )
    )


def _missing_filter_service():
    return SimpleNamespace(get_knowledge_filter=AsyncMock(return_value={"success": False}))


def _captured_scope():
    captured = {}

    async def capture(*_args, **_kwargs):
        captured["filters"] = get_search_filters()
        captured["limit"] = get_search_limit()
        captured["score_threshold"] = get_score_threshold()
        return {"response": "ok"}

    return captured, capture


SAVED_AURORA = {
    "data_sources": ["aurora.txt"],
    "document_types": ["*"],
    "owners": ["*"],
    "connector_types": ["*"],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("inline_filters", [None, {}, {"data_sources": ["borealis.txt"]}])
async def test_chat_endpoint_uses_saved_filter_over_request_copy(user, inline_filters):
    captured, capture = _captured_scope()
    chat_service = SimpleNamespace(chat=AsyncMock(side_effect=capture))
    service = _filter_service(SAVED_AURORA)

    await chat_api.chat_endpoint(
        chat_api.ChatBody(prompt="hi", filter_id="f1", filters=inline_filters),
        chat_service,
        None,
        user,
        knowledge_filter_service=service,
    )

    assert captured == {
        "filters": {"data_sources": ["aurora.txt"]},
        "limit": 5,
        "score_threshold": 0.4,
    }
    service.get_knowledge_filter.assert_awaited_once_with("f1", user_id="u1", jwt_token="jwt")


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_langflow_endpoint_uses_saved_filter(monkeypatch, user, native):
    monkeypatch.setattr(chat_api, "DISABLE_CHAT_WITH_LANGFLOW", native)
    captured, capture = _captured_scope()
    chat_service = SimpleNamespace(langflow_chat=AsyncMock(side_effect=capture))

    await chat_api.langflow_endpoint(
        chat_api.ChatBody(prompt="hi", filter_id="f1"),
        chat_service,
        None,
        user,
        knowledge_filter_service=_filter_service(SAVED_AURORA),
    )

    assert captured["filters"] == {"data_sources": ["aurora.txt"]}


@pytest.mark.asyncio
async def test_unscoped_saved_filter_sets_no_search_filters(user):
    captured, capture = _captured_scope()
    chat_service = SimpleNamespace(langflow_chat=AsyncMock(side_effect=capture))
    all_sources = {key: ["*"] for key in SAVED_AURORA}

    await chat_api.langflow_endpoint(
        chat_api.ChatBody(prompt="hi", filter_id="f1", filters={"data_sources": ["old.txt"]}),
        chat_service,
        None,
        user,
        knowledge_filter_service=_filter_service(all_sources),
    )

    assert captured["filters"] is None


@pytest.mark.asyncio
async def test_missing_filter_is_rejected(user):
    chat_service = SimpleNamespace(chat=AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_endpoint(
            chat_api.ChatBody(
                prompt="hi",
                filter_id="gone",
                filters={"data_sources": ["aurora.txt"]},
                limit=3,
                scoreThreshold=0.2,
            ),
            chat_service,
            None,
            user,
            knowledge_filter_service=_missing_filter_service(),
        )

    assert exc.value.status_code == 404
    chat_service.chat.assert_not_awaited()
    assert get_search_filters() is None


@pytest.mark.asyncio
async def test_request_without_filter_id_keeps_inline_filters(user):
    captured, capture = _captured_scope()
    chat_service = SimpleNamespace(chat=AsyncMock(side_effect=capture))
    service = _filter_service(SAVED_AURORA)

    await chat_api.chat_endpoint(
        chat_api.ChatBody(prompt="hi", filters={"owners": ["u2"]}),
        chat_service,
        None,
        user,
        knowledge_filter_service=service,
    )

    assert captured["filters"] == {"owners": ["u2"]}
    service.get_knowledge_filter.assert_not_awaited()
