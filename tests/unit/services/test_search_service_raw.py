"""Tests for the native equivalent of the flow's raw OpenSearch tool."""

from types import SimpleNamespace

import pytest

from auth_context import set_search_filters
from services.search_service import SearchService


@pytest.mark.asyncio
async def test_raw_search_tool_uses_the_user_client_and_fences_document_text(monkeypatch):
    captured = {}

    class Client:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return {"hits": {"hits": [{"_source": {"text": "Untrusted document"}}]}}

    service = SearchService.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: Client()
    )
    monkeypatch.setattr("services.search_service.get_auth_context", lambda: ("user", "jwt"))
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    set_search_filters({})

    result = await service.raw_search_tool('{"query":{"match_all":{}}}')

    assert captured["index"] == "documents"
    assert captured["body"] == {"query": {"match_all": {}}}
    assert result["hits"]["hits"][0]["_source"]["text"] == (
        "<<<UNTRUSTED_DOC_CHUNK>>>\nUntrusted document\n<<<END_UNTRUSTED_DOC_CHUNK>>>"
    )
