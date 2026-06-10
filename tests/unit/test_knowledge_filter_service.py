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
async def test_knowledge_filter_writes_use_admin_client_after_user_visibility_check(
    monkeypatch,
):
    user_client = SimpleNamespace(get_calls=[], write_calls=[])
    admin_client = SimpleNamespace(
        index_calls=[],
        update_calls=[],
        delete_calls=[],
        indices=_Indices(),
    )

    filter_doc = {
        "id": "filter-1",
        "name": "Test filter",
        "owner": "user-1",
        "query_data": "{}",
    }
    stored_doc = dict(filter_doc)

    async def get(*, index, id):
        user_client.get_calls.append({"index": index, "id": id})
        return {"found": True, "_source": dict(stored_doc)}

    async def user_index(**kwargs):
        user_client.write_calls.append(("index", kwargs))

    async def user_update(**kwargs):
        user_client.write_calls.append(("update", kwargs))

    async def user_delete(**kwargs):
        user_client.write_calls.append(("delete", kwargs))

    async def admin_index(**kwargs):
        admin_client.index_calls.append(kwargs)
        stored_doc.update(kwargs["body"])
        return {"result": "created"}

    async def admin_update(**kwargs):
        admin_client.update_calls.append(kwargs)
        stored_doc.update(kwargs["body"]["doc"])
        return {"result": "updated"}

    async def admin_delete(**kwargs):
        admin_client.delete_calls.append(kwargs)
        return {"result": "deleted"}

    user_client.get = get
    user_client.index = user_index
    user_client.update = user_update
    user_client.delete = user_delete
    admin_client.index = admin_index
    admin_client.update = admin_update
    admin_client.delete = admin_delete

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            assert user_id == "user-1"
            assert jwt_token == "Bearer user-token"
            return user_client

    monkeypatch.setattr(
        "config.settings.clients",
        SimpleNamespace(opensearch=admin_client),
    )

    service = KnowledgeFilterService(SessionManager())

    created = await service.create_knowledge_filter(
        filter_doc, user_id="user-1", jwt_token="Bearer user-token"
    )
    updated = await service.update_knowledge_filter(
        "filter-1",
        {"description": "Updated"},
        user_id="user-1",
        jwt_token="Bearer user-token",
    )
    deleted = await service.delete_knowledge_filter(
        "filter-1", user_id="user-1", jwt_token="Bearer user-token"
    )

    assert created["success"] is True
    assert updated["success"] is True
    assert deleted["success"] is True
    assert admin_client.index_calls[0]["index"] == KNOWLEDGE_FILTERS_INDEX_NAME
    assert admin_client.update_calls[0]["index"] == KNOWLEDGE_FILTERS_INDEX_NAME
    assert admin_client.delete_calls[0]["index"] == KNOWLEDGE_FILTERS_INDEX_NAME
    assert user_client.write_calls == []
    assert user_client.get_calls == [
        {"index": KNOWLEDGE_FILTERS_INDEX_NAME, "id": "filter-1"},
        {"index": KNOWLEDGE_FILTERS_INDEX_NAME, "id": "filter-1"},
        {"index": KNOWLEDGE_FILTERS_INDEX_NAME, "id": "filter-1"},
    ]

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
    for knowledge_filter in result["filters"]:
        assert "active_source_count" not in knowledge_filter


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
