from types import SimpleNamespace

import pytest

from services.knowledge_filter_service import (
    KNOWLEDGE_FILTERS_INDEX_NAME,
    KnowledgeFilterService,
)


class _Indices:
    async def refresh(self, index):
        return {"acknowledged": True, "index": index}


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
