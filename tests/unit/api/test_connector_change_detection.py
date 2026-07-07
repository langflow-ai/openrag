"""Unit tests for bucket-connector change detection in `src/api/connectors.py`.

Covers:
- the pure timestamp/classification helpers (`_parse_iso_to_epoch_ms`,
  `remote_is_newer_than_synced`, `classify_remote_file_change`),
- the `get_synced_id_to_modified_time_map` aggregation helper,
- the whole-container (`bucket_filter`) reconciliation in `connector_sync`: only
  new + changed blobs are ingested (new as a plain batch, changed with
  replace_duplicates=True), unchanged blobs are skipped.
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


def _json(response):
    return json.loads(response.body.decode())


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_iso_to_epoch_ms_handles_z_and_offset_and_naive():
    from api.connectors import _parse_iso_to_epoch_ms

    z = _parse_iso_to_epoch_ms("2024-01-01T00:00:00Z")
    offset = _parse_iso_to_epoch_ms("2024-01-01T00:00:00+00:00")
    naive = _parse_iso_to_epoch_ms("2024-01-01T00:00:00")
    assert z == offset == naive == 1704067200000.0


def test_parse_iso_to_epoch_ms_returns_none_for_bad_input():
    from api.connectors import _parse_iso_to_epoch_ms

    assert _parse_iso_to_epoch_ms(None) is None
    assert _parse_iso_to_epoch_ms("") is None
    assert _parse_iso_to_epoch_ms("not-a-date") is None


def test_remote_is_newer_than_synced_true_when_strictly_newer():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": 1704067200000.0}  # 2024-01-01
    assert remote_is_newer_than_synced("c::a", "2024-06-01T00:00:00Z", stored) is True


def test_remote_is_newer_than_synced_false_when_same_or_older():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": 1704067200000.0}
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:00Z", stored) is False
    assert remote_is_newer_than_synced("c::a", "2023-01-01T00:00:00Z", stored) is False


def test_remote_is_newer_than_synced_tolerance_absorbs_subsecond_jitter():
    from api.connectors import remote_is_newer_than_synced

    stored = {"c::a": 1704067200000.0}
    # 500ms newer is within tolerance → not "changed".
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:00.500Z", stored) is False
    # 2s newer exceeds tolerance → changed.
    assert remote_is_newer_than_synced("c::a", "2024-01-01T00:00:02Z", stored) is True


def test_remote_is_newer_than_synced_false_when_no_stored_token():
    from api.connectors import remote_is_newer_than_synced

    # Missing id, or ingested-but-no-token (None) → backfill-safe False.
    assert remote_is_newer_than_synced("c::missing", "2024-06-01T00:00:00Z", {}) is False
    assert remote_is_newer_than_synced("c::a", "2024-06-01T00:00:00Z", {"c::a": None}) is False


def test_classify_remote_file_change():
    from api.connectors import classify_remote_file_change

    stored = {"c::a": 1704067200000.0}
    # Not ingested → new (regardless of timestamps).
    assert classify_remote_file_change("c::new", "2024-06-01T00:00:00Z", False, stored) == "new"
    # Ingested + newer → changed.
    assert classify_remote_file_change("c::a", "2024-06-01T00:00:00Z", True, stored) == "changed"
    # Ingested + same → unchanged.
    assert classify_remote_file_change("c::a", "2024-01-01T00:00:00Z", True, stored) == "unchanged"
    # Ingested but no stored token (backfill) → unchanged.
    assert classify_remote_file_change("c::b", "2024-06-01T00:00:00Z", True, {}) == "unchanged"


# ---------------------------------------------------------------------------
# get_synced_id_to_modified_time_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modified_time_map_prefers_connector_file_id_over_document_id(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "by_connector_file_id": {
                    "buckets": [
                        {"key": "c::a", "latest_modified": {"value": 1704067200000.0}},
                        # connector_file_id present but no modified_time → None
                        {"key": "c::b", "latest_modified": {"value": None}},
                    ]
                },
                "by_document_id": {
                    "buckets": [
                        # Langflow-path id (document_id holds the connector source id).
                        {"key": "c::lf", "latest_modified": {"value": 1704153600000.0}},
                        # A content-hash document_id from the standard path — harmless,
                        # never matches an enumerated source id. Overlaid/ignored.
                        {"key": "c::a", "latest_modified": {"value": 999.0}},
                    ]
                },
            }
        }
    )
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_modified_time_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )

    # connector_file_id wins for c::a (1704067200000, not the 999 from document_id).
    assert result["c::a"] == 1704067200000.0
    assert result["c::b"] is None
    assert result["c::lf"] == 1704153600000.0


@pytest.mark.asyncio
async def test_modified_time_map_returns_empty_on_error(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(side_effect=RuntimeError("boom"))
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    result = await connectors_api.get_synced_id_to_modified_time_map(
        connector_type="azure_blob",
        user_id="alice",
        session_manager=sm,
        jwt_token=None,
    )
    assert result == {}


# ---------------------------------------------------------------------------
# connector_sync — bucket_filter reconciliation
# ---------------------------------------------------------------------------


def _bucket_sync_service(remote_files, task_id="task-x"):
    connection = SimpleNamespace(connection_id="conn-1", is_active=True)
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)
    connector.bucket_names = None
    connector.list_files = AsyncMock(return_value={"files": remote_files, "next_page_token": None})

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock(return_value=task_id)
    return service


@pytest.mark.asyncio
async def test_bucket_filter_ingests_only_new_and_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    # "c::ingested_unchanged" and "c::ingested_changed" are already ingested.
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(
            return_value=(["c::ingested_unchanged", "c::ingested_changed"], [], "connector_file_id")
        ),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(
            return_value={
                "c::ingested_unchanged": 1704067200000.0,  # 2024-01-01
                "c::ingested_changed": 1704067200000.0,  # 2024-01-01
            }
        ),
    )

    remote_files = [
        {"id": "c::new", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::ingested_unchanged", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::ingested_changed", "modified_time": "2024-06-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    assert _json(response)["task_ids"] == ["task-x", "task-x"]

    # Two batches: new (replace defaulted False) + changed (replace=True).
    assert service.sync_specific_files.await_count == 2
    new_call, changed_call = service.sync_specific_files.await_args_list
    assert new_call.args[2] == ["c::new"]
    assert new_call.kwargs.get("replace_duplicates", False) is False
    assert changed_call.args[2] == ["c::ingested_changed"]
    assert changed_call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_bucket_filter_all_unchanged_returns_no_files(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(return_value={"c::a": 1704067200000.0, "c::b": 1704067200000.0}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 200
    body = _json(response)
    assert body["status"] == "no_files"
    assert "up to date" in body["message"]
    service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_bucket_filter_only_new_files_single_batch(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=([], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(return_value={}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(connection_id="conn-1", bucket_filter=["c"]),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::a", "c::b"]
    assert call.kwargs.get("replace_duplicates", False) is False


# ---------------------------------------------------------------------------
# bucket_changed_file_ids — updates-only change detection helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_filters_to_changed_ingested(monkeypatch):
    """Only already-ingested blobs that are newer at source are returned; new
    (un-ingested) blobs are ignored (updates-only)."""
    from api import connectors as connectors_api

    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(
            return_value={"c::a": 1704067200000.0, "c::b": 1704067200000.0}  # 2024-01-01
        ),
    )

    connector = MagicMock()
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
                {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
                {"id": "c::new", "modified_time": "2024-06-01T00:00:00Z"},  # new → ignored
            ],
            "next_page_token": None,
        }
    )

    changed = await connectors_api.bucket_changed_file_ids(
        connector,
        "azure_blob",
        "alice",
        MagicMock(),
        "token",
        ["c::a", "c::b"],
    )
    assert changed == ["c::b"]


@pytest.mark.asyncio
async def test_bucket_changed_file_ids_empty_when_no_existing():
    from api import connectors as connectors_api

    connector = MagicMock()
    connector.list_files = AsyncMock()
    changed = await connectors_api.bucket_changed_file_ids(
        connector, "azure_blob", "alice", MagicMock(), "token", []
    )
    assert changed == []
    connector.list_files.assert_not_awaited()


# ---------------------------------------------------------------------------
# connector_sync (Sync button, no selected_files/sync_all/bucket_filter) —
# updates-only re-ingest for bucket connectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_button_bucket_reingests_only_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(return_value={"c::a": 1704067200000.0, "c::b": 1704067200000.0}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
        {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(),  # plain Sync: no files, no sync_all/bucket_filter
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::b"]
    assert call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_sync_button_bucket_all_unchanged_returns_no_files(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(return_value={"c::a": 1704067200000.0, "c::b": 1704067200000.0}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},
        {"id": "c::b", "modified_time": "2024-01-01T00:00:00Z"},
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.connector_sync(
        "azure_blob",
        connectors_api.ConnectorSyncBody(),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 200
    body = _json(response)
    assert body["status"] == "no_files"
    assert "up to date" in body["message"]
    service.sync_specific_files.assert_not_awaited()


# ---------------------------------------------------------------------------
# sync_all_connectors — updates-only re-ingest for bucket connectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_all_bucket_reingests_only_changed(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(
        connectors_api,
        "_allowed_connector_types_for_request",
        AsyncMock(return_value=["azure_blob"]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["c::a", "c::b"], [], "connector_file_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        connectors_api,
        "get_synced_id_to_modified_time_map",
        AsyncMock(return_value={"c::a": 1704067200000.0, "c::b": 1704067200000.0}),
    )

    remote_files = [
        {"id": "c::a", "modified_time": "2024-01-01T00:00:00Z"},  # unchanged
        {"id": "c::b", "modified_time": "2024-06-01T00:00:00Z"},  # changed
    ]
    service = _bucket_sync_service(remote_files)

    response = await connectors_api.sync_all_connectors(
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    call = service.sync_specific_files.await_args
    assert call.args[2] == ["c::b"]
    assert call.kwargs["replace_duplicates"] is True
