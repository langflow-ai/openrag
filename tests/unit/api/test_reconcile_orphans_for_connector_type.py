"""Unit tests for `reconcile_orphans_for_connector_type` in `src/api/connectors.py`.

The orphan-deletion safety net must:
- compute orphans from indexed IDs minus the union of active remote IDs,
- abort on unauthenticated or failing connector listings,
- preserve files present in any active connection,
- enumerate visible chunks with the user-scoped client, then delete by primary
  ID with the trusted backend OpenSearch client,
- query either `document_id` or `connector_file_id` depending on the ingest path.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_connection(connection_id: str, is_active: bool = True):
    return SimpleNamespace(connection_id=connection_id, is_active=is_active)


def _make_connector(remote_file_ids, *, authenticated=True, raise_on_list=False):
    connector = MagicMock()
    connector.is_authenticated = authenticated
    if raise_on_list:
        connector.list_files = AsyncMock(side_effect=RuntimeError("graph 503"))
    else:
        connector.list_files = AsyncMock(
            return_value={"files": [{"id": fid} for fid in remote_file_ids]}
        )
    return connector


def _make_service(connections, connector_lookup):
    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=connections)

    async def _get_connector(connection_id):
        return connector_lookup.get(connection_id)

    service.get_connector = AsyncMock(side_effect=_get_connector)
    return service


def _make_opensearch_client(chunk_ids: list[str] | None = None):
    client = AsyncMock()
    hits = [{"_id": cid} for cid in (chunk_ids or [])]
    client.search = AsyncMock(return_value={"_scroll_id": None, "hits": {"hits": hits}})
    client.delete = AsyncMock(return_value={"result": "deleted"})
    client.delete_by_query = AsyncMock()
    return client


def _make_session_manager(opensearch_client):
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    return sm


def _json(response):
    return json.loads(response.body.decode())


def _patch_write_client(monkeypatch, *, delete_side_effect=None):
    write_client = AsyncMock()
    write_client.delete = AsyncMock(
        side_effect=delete_side_effect,
        return_value={"result": "deleted"},
    )
    write_client.delete_by_query = AsyncMock()
    monkeypatch.setattr("config.settings.clients.opensearch", write_client)
    monkeypatch.setattr("api.connectors.get_index_name", lambda: "test-index")
    return write_client


@pytest.mark.asyncio
async def test_empty_existing_file_ids_returns_empty_without_calls():
    from api.connectors import reconcile_orphans_for_connector_type

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock()
    sm = _make_session_manager(AsyncMock())

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=[],
    )

    assert result == []
    service.connection_manager.list_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_active_connections_skips_reconcile():
    from api.connectors import reconcile_orphans_for_connector_type

    inactive = [_make_connection("c1", is_active=False)]
    service = _make_service(inactive, connector_lookup={})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthenticated_connection_aborts_pass():
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    connector.list_files.assert_not_awaited()
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_listing_exception_aborts_pass():
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], raise_on_list=True)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_orphans_skips_delete_call():
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "b"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_happy_path_deletes_orphans(monkeypatch):
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "c"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-b-1", "chunk-b-2"])
    write_client = _patch_write_client(monkeypatch)
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert result == ["b"]
    opensearch_client.delete_by_query.assert_not_awaited()
    write_client.delete_by_query.assert_not_awaited()
    opensearch_client.delete.assert_not_awaited()

    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"document_id": ["b"]}}
    assert [call.kwargs["id"] for call in write_client.delete.await_args_list] == [
        "chunk-b-1",
        "chunk-b-2",
    ]


@pytest.mark.asyncio
async def test_delete_failure_does_not_raise(monkeypatch):
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-b-1"])
    _patch_write_client(monkeypatch, delete_side_effect=RuntimeError("opensearch unavailable"))
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []


@pytest.mark.asyncio
async def test_multi_connection_union_preserves_files_present_in_any_connection():
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=["b"])
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_connection_one_offline_aborts_even_if_other_succeeds():
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_paginated_listing_aggregates_all_pages():
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = MagicMock()
    connector.is_authenticated = True
    pages = [
        {"files": [{"id": "a"}], "nextPageToken": "tok-1"},
        {"files": [{"id": "b"}, {"id": "c"}]},
    ]
    connector.list_files = AsyncMock(side_effect=pages)

    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert result == []
    assert connector.list_files.await_count == 2
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_file_id_field_used_when_specified(monkeypatch):
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["sp-guid-a"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-b-0", "chunk-b-1"])
    write_client = _patch_write_client(monkeypatch)
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["sp-guid-a", "sp-guid-b"],
        id_field="connector_file_id",
    )

    assert result == ["sp-guid-b"]
    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"connector_file_id": ["sp-guid-b"]}}
    assert write_client.delete.await_count == 2
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_id_field_used_by_default(monkeypatch):
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["lf-id-a"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-lf-b-0"])
    write_client = _patch_write_client(monkeypatch)
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["lf-id-a", "lf-id-b"],
    )

    assert result == ["lf-id-b"]
    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"document_id": ["lf-id-b"]}}
    write_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_subtracts_orphans_from_resync_count(monkeypatch):
    from api.connectors import _preview_orphans_for_connector_type

    monkeypatch.setattr(
        "api.connectors.get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["a", "b", "c", "d", "e", "f"], [], "document_id")),
    )
    monkeypatch.setattr(
        "api.connectors.get_synced_id_to_filename_map",
        AsyncMock(return_value={"b": "b.pdf", "e": "e.pdf"}),
    )
    monkeypatch.setattr(
        "api.connectors.compute_orphans_for_connector_type",
        AsyncMock(
            return_value=[
                {"document_id": "b", "filename": "b.pdf"},
                {"document_id": "e", "filename": "e.pdf"},
            ]
        ),
    )

    orphans, synced_count = await _preview_orphans_for_connector_type(
        connector_type="google_drive",
        user_id="alice",
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        jwt_token="token",
    )

    assert synced_count == 4
    assert orphans == [
        {"document_id": "b", "filename": "b.pdf"},
        {"document_id": "e", "filename": "e.pdf"},
    ]


@pytest.mark.asyncio
async def test_connector_sync_filters_orphan_ids_before_resync(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["a", "b", "c", "d", "e", "f"], [], "document_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=["b", "e"]),
    )

    connection = _make_connection("conn-1")
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock(return_value="task-1")

    response = await connectors_api.connector_sync(
        "google_drive",
        connectors_api.ConnectorSyncBody(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    args = service.sync_specific_files.await_args.args
    assert args[2] == ["a", "c", "d", "f"]


@pytest.mark.asyncio
async def test_connector_sync_returns_no_files_when_all_ids_are_orphans(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["a", "b"], [], "document_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=["a", "b"]),
    )

    connection = _make_connection("conn-1")
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock()

    response = await connectors_api.connector_sync(
        "google_drive",
        connectors_api.ConnectorSyncBody(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
    )

    assert response.status_code == 200
    assert _json(response)["status"] == "no_files"
    service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_all_returns_deleted_only_without_error(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())

    async def fake_synced_ids(connector_type, *args, **kwargs):
        if connector_type == "google_drive":
            return ["a", "b"], [], "document_id"
        return [], [], "document_id"

    monkeypatch.setattr(connectors_api, "get_synced_file_ids_for_connector", fake_synced_ids)
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=["a", "b"]),
    )

    connection = _make_connection("conn-1")
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock()

    response = await connectors_api.sync_all_connectors(
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
    )

    body = _json(response)
    assert response.status_code == 200
    assert body["status"] == "no_files"
    assert body.get("errors") is None
    assert body["deleted_only_connectors"] == ["google_drive"]
    assert "Deleted stale cloud files" in body["message"]
    service.sync_specific_files.assert_not_awaited()
