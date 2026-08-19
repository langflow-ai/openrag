import pytest

from api.documents import delete_documents_by_filename_core


class FakeOpenSearchClient:
    def __init__(self, owned_hits=None, visible_hits=None, remaining_source_hits=None):
        """Initialize deterministic search results and recorded calls."""
        self.owned_hits = owned_hits or []
        self.visible_hits = visible_hits or []
        self.remaining_source_hits = remaining_source_hits or []
        self.search_calls = []
        self.delete_calls = []

    async def search(self, *, index, body, scroll=None):
        self.search_calls.append({"index": index, "body": body, "scroll": scroll})
        query = body["query"]
        if "wildcard" in query:
            hits = self.remaining_source_hits
        elif "bool" in query:
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
async def test_delete_documents_by_filename_deletes_ownerless_with_anonymous_permission(
    monkeypatch,
):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        visible_hits=[{"_id": "shared-chunk", "_source": {}}],
    )
    backend_opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {"_id": "shared-chunk-1", "_source": {}},
            {"_id": "shared-chunk-2", "_source": {}},
        ]
    )
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename="shared.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
        can_delete_own=False,
        can_delete_anonymous=True,
    )

    assert status_code == 200
    assert payload["success"] is True
    assert payload["deleted_chunks"] == 2
    assert opensearch_client.search_calls == []
    assert backend_opensearch_client.search_calls[0]["body"]["query"] == {
        "bool": {
            "filter": [
                {"term": {"filename": "shared.pdf"}},
                {"bool": {"must_not": {"exists": {"field": "owner"}}}},
            ]
        }
    }
    assert backend_opensearch_client.delete_calls == [
        {"index": "documents", "id": "shared-chunk-1", "refresh": True},
        {"index": "documents", "id": "shared-chunk-2", "refresh": True},
    ]


@pytest.mark.asyncio
async def test_delete_documents_by_filename_combines_owned_and_anonymous_scopes(monkeypatch):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient()
    backend_opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {"_id": "owned-chunk", "_source": {"owner": "user-1"}},
            {"_id": "anonymous-chunk", "_source": {}},
        ]
    )
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename="shared.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
        can_delete_own=True,
        can_delete_anonymous=True,
    )

    assert status_code == 200
    assert payload["deleted_chunks"] == 2
    assert backend_opensearch_client.search_calls[0]["body"]["query"] == {
        "bool": {
            "filter": [
                {"term": {"filename": "shared.pdf"}},
                {
                    "bool": {
                        "should": [
                            {"term": {"owner": "user-1"}},
                            {"bool": {"must_not": {"exists": {"field": "owner"}}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            ]
        }
    }


@pytest.mark.asyncio
async def test_delete_documents_by_filename_denies_ownerless_without_anonymous_permission(
    monkeypatch,
):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[],
        visible_hits=[{"_id": "shared-chunk", "_source": {}}],
    )

    payload, status_code = await delete_documents_by_filename_core(
        filename="shared.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
        can_delete_own=True,
        can_delete_anonymous=False,
    )

    assert status_code == 403
    assert payload["success"] is False
    assert payload["deleted_chunks"] == 0
    assert "only the document owner" in payload["error"]
    assert opensearch_client.delete_calls == []


@pytest.mark.asyncio
async def test_delete_documents_by_filename_denies_when_no_delete_scope(monkeypatch):
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient()

    payload, status_code = await delete_documents_by_filename_core(
        filename="shared.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
        can_delete_own=False,
        can_delete_anonymous=False,
    )

    assert status_code == 403
    assert payload["success"] is False
    assert "insufficient permissions" in payload["error"]
    assert opensearch_client.search_calls == []


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


@pytest.mark.asyncio
async def test_delete_documents_by_filename_removes_unreferenced_local_source(
    monkeypatch, tmp_path
):
    """Remove a local source archive after its final chunk is deleted."""
    document_id = "abcdefghijklmnopqrstuvwx"
    source_id = f"{document_id}.{'a' * 32}"
    archived = tmp_path / ".openrag-indexed" / source_id / "report.pdf"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"pdf")

    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {
                "_id": "chunk-1",
                "_source": {
                    "document_id": document_id,
                    "source_url": f"/api/source-files/{source_id}",
                },
            }
        ]
    )
    backend_opensearch_client = FakeOpenSearchClient()
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename="report.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 200
    assert payload["deleted_chunks"] == 1
    assert not archived.parent.exists()
    assert backend_opensearch_client.search_calls[-1]["body"]["query"] == {
        "wildcard": {
            "source_url": {"value": f"*/api/source-files/{source_id}"},
        }
    }


@pytest.mark.asyncio
async def test_delete_documents_by_filename_keeps_still_referenced_local_source(
    monkeypatch, tmp_path
):
    """Keep a local source archive while another chunk still references it."""
    document_id = "abcdefghijklmnopqrstuvwx"
    source_id = f"{document_id}.{'b' * 32}"
    archived = tmp_path / ".openrag-indexed" / source_id / "report.pdf"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"pdf")

    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {
                "_id": "chunk-1",
                "_source": {
                    "document_id": document_id,
                    "source_url": f"/api/source-files/{source_id}",
                },
            }
        ]
    )
    backend_opensearch_client = FakeOpenSearchClient(remaining_source_hits=[{"_id": "other-chunk"}])
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename="report.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 200
    assert archived.exists()


@pytest.mark.asyncio
async def test_delete_documents_by_filename_never_deletes_remote_source(monkeypatch):
    """Never treat a remote source URL as a backend-managed archive."""
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    opensearch_client = FakeOpenSearchClient(
        owned_hits=[
            {
                "_id": "chunk-1",
                "_source": {
                    "document_id": "abcdefghijklmnopqrstuvwx",
                    "source_url": "https://openarchiver.example.com/documents/123",
                },
            }
        ]
    )
    backend_opensearch_client = FakeOpenSearchClient()
    monkeypatch.setattr("config.settings.clients.opensearch", backend_opensearch_client)

    payload, status_code = await delete_documents_by_filename_core(
        filename="report.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user_id="user-1",
        jwt_token="jwt-token",
    )

    assert status_code == 200
    assert backend_opensearch_client.search_calls == []
