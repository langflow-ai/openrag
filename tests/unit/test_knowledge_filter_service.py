from types import SimpleNamespace

import json
import pytest

from services.knowledge_filter_service import (
    KNOWLEDGE_FILTERS_INDEX_NAME,
    KnowledgeFilterService,
)

class _Indices:
    async def refresh(self, index):
        return {"acknowledged": True, "index": index}
    

def _filter(filter_id, data_sources=None, query_data=None):
    if query_data is None:
        query_data = json.dumps({"filters": {"data_sources": data_sources}}) if data_sources else "{}"
    return {"id": filter_id, "name": filter_id, "query_data": query_data}


def _setup_search(monkeypatch, filters, existing_filenames):
    """Service whose user client returns `filters` from search, and whose
    admin client's existence-check aggregation returns `existing_filenames`.
    """

    async def user_search(*, index, body):
        return {"hits": {"hits": [{"_source": f, "_score": 1.0} for f in filters]}}

    admin_client = SimpleNamespace(search_calls=[])

    async def admin_search(*, index, body):
        admin_client.search_calls.append(body)
        return {
            "aggregations": {
                "filenames": {"buckets": [{"key": name} for name in existing_filenames]}
            }
        }

    admin_client.search = admin_search

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            return SimpleNamespace(search=user_search)

    monkeypatch.setattr("config.settings.clients", SimpleNamespace(opensearch=admin_client))
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")

    return KnowledgeFilterService(SessionManager()), admin_client


@pytest.mark.asyncio
async def test_search_knowledge_filters_active_source_count_zero_when_document_deleted(
    monkeypatch,
):
    filters = [_filter("filter-1", data_sources=["README.md"])]
    service, admin_client = _setup_search(monkeypatch, filters, existing_filenames=set())

    result = await service.search_knowledge_filters("", user_id="user-1", jwt_token="token")

    assert result["success"] is True
    assert result["filters"][0]["active_source_count"] == 0
    assert len(admin_client.search_calls) == 1


@pytest.mark.asyncio
async def test_search_knowledge_filters_malformed_query_data_fails_silently(monkeypatch):
    filters = [
        _filter("filter-1", query_data="not json"),
        _filter("filter-2", data_sources=["a.md"]),
    ]
    service, _ = _setup_search(monkeypatch, filters, existing_filenames={"a.md"})

    result = await service.search_knowledge_filters("", user_id="user-1", jwt_token="token")

    assert result["success"] is True
    assert len(result["filters"]) == 2
    assert "active_source_count" not in result["filters"][0]  # malformed filter
    assert result["filters"][1]["active_source_count"] == 1  # valid filter


@pytest.mark.asyncio
async def test_search_knowledge_filters_dedups_shared_filenames_in_one_query(monkeypatch):
    filters = [
        _filter("filter-1", data_sources=["shared.pdf"]),
        _filter("filter-2", data_sources=["shared.pdf"]),
    ]
    service, admin_client = _setup_search(monkeypatch, filters, existing_filenames={"shared.pdf"})

    result = await service.search_knowledge_filters("", user_id="user-1", jwt_token="token")

    assert len(admin_client.search_calls) == 1
    assert admin_client.search_calls[0]["query"]["terms"]["filename"] == ["shared.pdf"]
    assert result["filters"][0]["active_source_count"] == 1
    assert result["filters"][1]["active_source_count"] == 1
