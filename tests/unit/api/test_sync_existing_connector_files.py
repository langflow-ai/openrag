"""Outcome contract of _sync_existing_connector_files — the shared
no-selection Sync flow behind both connector_sync and sync_all_connectors."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api import connectors as connectors_api


def _make_services():
    connector_service = MagicMock()
    connector_service.sync_specific_files = AsyncMock(return_value="task-1")
    connector_service.sync_connector_files = AsyncMock(return_value="task-2")
    connector_service.get_connector = AsyncMock(return_value=MagicMock())
    working_connection = MagicMock()
    working_connection.connection_id = "conn-1"
    return connector_service, working_connection


async def _run(
    connector_service,
    working_connection,
    *,
    connector_type="google_drive",
    existing_file_ids=None,
    existing_filenames=None,
    **kwargs,
):
    return await connectors_api._sync_existing_connector_files(
        connector_type=connector_type,
        working_connection=working_connection,
        user_id="user-1",
        connector_service=connector_service,
        session_manager=MagicMock(),
        jwt_token="jwt",
        existing_file_ids=existing_file_ids or [],
        existing_filenames=existing_filenames or [],
        id_field="connector_file_id",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_oauth_sync_uses_connector_replace_capability(monkeypatch):
    monkeypatch.setattr(
        connectors_api, "reconcile_orphans_for_connector_type", AsyncMock(return_value=[])
    )
    connector_service, working_connection = _make_services()

    result = await _run(connector_service, working_connection, existing_file_ids=["f1", "f2"])

    assert result == {"outcome": "synced", "task_id": "task-1"}
    call = connector_service.sync_specific_files.await_args
    assert call.args[2] == ["f1", "f2"]
    # google_drive declares SYNC_REPLACES_DUPLICATES=True.
    assert call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_deleted_only_when_orphan_reconcile_removes_everything(monkeypatch):
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=["f1", "f2"]),
    )
    connector_service, working_connection = _make_services()

    result = await _run(connector_service, working_connection, existing_file_ids=["f1", "f2"])

    assert result == {"outcome": "deleted_only"}
    connector_service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_false_skips_orphan_pass(monkeypatch):
    reconcile = AsyncMock(return_value=["f1"])
    monkeypatch.setattr(connectors_api, "reconcile_orphans_for_connector_type", reconcile)
    connector_service, working_connection = _make_services()

    result = await _run(
        connector_service,
        working_connection,
        existing_file_ids=["f1"],
        reconcile=False,
    )

    assert result["outcome"] == "synced"
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_timestamp_connector_up_to_date_when_no_changes(monkeypatch):
    monkeypatch.setattr(
        connectors_api, "reconcile_orphans_for_connector_type", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(connectors_api, "bucket_changed_file_ids", AsyncMock(return_value=[]))
    connector_service, working_connection = _make_services()

    result = await _run(
        connector_service,
        working_connection,
        connector_type="aws_s3",
        existing_file_ids=["k1"],
    )

    assert result == {"outcome": "up_to_date"}
    connector_service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_timestamp_connector_syncs_only_changed_ids_with_replace(monkeypatch):
    monkeypatch.setattr(
        connectors_api, "reconcile_orphans_for_connector_type", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(connectors_api, "bucket_changed_file_ids", AsyncMock(return_value=["k2"]))
    connector_service, working_connection = _make_services()

    result = await _run(
        connector_service,
        working_connection,
        connector_type="aws_s3",
        existing_file_ids=["k1", "k2"],
    )

    assert result == {"outcome": "synced", "task_id": "task-1"}
    call = connector_service.sync_specific_files.await_args
    assert call.args[2] == ["k2"]
    assert call.kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_filename_fallback_when_no_ids(monkeypatch):
    connector_service, working_connection = _make_services()

    result = await _run(
        connector_service,
        working_connection,
        existing_filenames=["a.pdf", "b.pdf"],
    )

    assert result == {"outcome": "synced", "task_id": "task-2"}
    call = connector_service.sync_connector_files.await_args
    assert call.kwargs["filename_filter"] == {"a.pdf", "b.pdf"}
