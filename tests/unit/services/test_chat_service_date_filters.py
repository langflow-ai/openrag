"""ChatService forwards saved date ranges in the Langflow query-filter header."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import agent
from auth_context import set_search_filters
from services.chat_service import ChatService

HEADER = "X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"
RANGE = {
    "range": {"indexed_time": {"gte": "2026-10-07T07:00:00Z", "lte": "2026-10-11T06:59:59.999Z"}}
}
PDF = {"term": {"mimetype": "application/pdf"}}
SAMPLE_EXCLUSION = {"bool": {"must_not": [{"term": {"is_sample_data": "true"}}]}}
DATES = {"created_after": "2026-10-07T07:00:00Z", "created_before": "2026-10-11T06:59:59.999Z"}


@pytest.fixture
def captured(monkeypatch):
    monkeypatch.setattr("services.chat_service.LANGFLOW_URL", "http://lf")
    monkeypatch.setattr("services.chat_service.LANGFLOW_CHAT_FLOW_ID", "chat")
    monkeypatch.setattr("services.chat_service.NUDGES_FLOW_ID", "nudges")
    monkeypatch.setattr(
        "services.chat_service.clients.ensure_langflow_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr("utils.langflow_headers.add_provider_credentials_to_headers", AsyncMock())
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="m",
                embedding_provider=None,
                chunk_size=1000,
                chunk_overlap=200,
                index_name="documents",
            )
        ),
    )
    monkeypatch.setattr(
        "services.langflow_ingest_token_service.LangflowIngestTokenService.create_token",
        lambda self, context: "tok",
    )
    seen = {}

    async def fake_chat(client, flow_id, prompt, user_id, **kwargs):
        seen["headers"] = kwargs["extra_headers"]
        return "ok", "rid", []

    monkeypatch.setattr(agent, "async_langflow_chat", fake_chat)
    return seen


def _filter_expression(seen):
    return json.loads(seen["headers"][HEADER])


@pytest.mark.asyncio
async def test_chat_header_carries_pdf_and_date_range(captured):
    set_search_filters({"document_types": ["application/pdf"], **DATES})
    try:
        await ChatService().langflow_chat(prompt="hi", user_id="u")
    finally:
        set_search_filters(None)
    assert _filter_expression(captured)["filter"] == [PDF, RANGE]


@pytest.mark.asyncio
async def test_nudges_date_only_filter_sends_range_without_sample_exclusion(captured):
    await ChatService().langflow_nudges_chat(user_id="u", filters=dict(DATES))
    clauses = _filter_expression(captured)["filter"]
    assert clauses == [RANGE]
    assert SAMPLE_EXCLUSION not in clauses


@pytest.mark.asyncio
async def test_nudges_unrestricted_request_still_excludes_sample_data(captured):
    await ChatService().langflow_nudges_chat(user_id="u", filters=None)
    assert _filter_expression(captured)["filter"] == [SAMPLE_EXCLUSION]
