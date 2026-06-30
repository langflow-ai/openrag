import pytest

from api.documents import delete_documents_by_filename_core


class FakeOpenSearchClient:
    def __init__(self, owned_hits=None, visible_hits=None):
        self.owned_hits = owned_hits or []
        self.visible_hits = visible_hits or []
        self.search_calls = []
        self.delete_calls = []

    async def search(self, *, index, body, scroll=None):
        self.search_calls.append({"index": index, "body": body, "scroll": scroll})
        query = body["query"]
        if "bool" in query:
            hits = self.owned_hits
        else:
            hits = self.visible_hits
        return {"hits": {"hits": hits}}

    async def delete(self, *, index, id, refresh=True):
        self.delete_calls.append({"index": index, "id": id, "refresh": refresh})
        return {"result": "deleted"}


class FakeSessionManager:
    def __init__(self, opensearch_client):
        self.opensearch_client = opensearch_client

    def get_user_opensearch_client(self, user_id, jwt_token):
        assert user_id == "user-1"
        assert jwt_token == "jwt-token"
        return self.opensearch_client


@pytest.mark.asyncio
async def test_delete_documents_by_filename_deletes_owned_ids_with_backend_client(monkeypatch):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {"_id": "chunk-1", "_source": {"owner": "user-1"}},
            {"_id": "chunk-2", "_source": {"owner": "user-1"}},
        ]
    )
    backend_opensearch_client = FakeOpenSearchClient()
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename=" report.pdf ",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 200
    assert payload["success"] is True
    assert payload["deleted_chunks"] == 2
    assert len(opensearch_client.search_calls) == 1
    assert opensearch_client.search_calls[0]["body"]["query"] == {
        "bool": {
            "filter": [
                {"term": {"filename": "report.pdf"}},
                {"term": {"owner": "user-1"}},
            ]
        }
    }
    assert opensearch_client.delete_calls == []
    assert backend_opensearch_client.delete_calls == [
        {"index": "documents", "id": "chunk-1", "refresh": True},
        {"index": "documents", "id": "chunk-2", "refresh": True},
    ]


@pytest.mark.asyncio
async def test_delete_documents_by_filename_denies_visible_non_owner(monkeypatch):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[],
        visible_hits=[{"_id": "shared-chunk", "_source": {"owner": "other-user"}}],
    )

    payload, status_code = await delete_documents_by_filename_core(
        filename="shared.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 403
    assert payload["success"] is False
    assert payload["deleted_chunks"] == 0
    assert "only the document owner" in payload["error"]
    assert opensearch_client.delete_calls == []


@pytest.mark.asyncio
async def test_delete_documents_by_filename_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(owned_hits=[], visible_hits=[])

    payload, status_code = await delete_documents_by_filename_core(
        filename="missing.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 404
    assert payload["success"] is False
    assert payload["deleted_chunks"] == 0
    assert opensearch_client.delete_calls == []
