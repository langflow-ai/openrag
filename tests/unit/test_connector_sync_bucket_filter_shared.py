"""Regression test: connector_sync's bucket_filter branch must forward
`shared` to both sync_specific_files batches (new + changed files).

This is the code path the COS connector UI's "Ingest N Buckets" button
always hits (it sends bucket_filter, never selected_files/sync_all), so a
dropped `shared` here means the "Make documents available to all users"
toggle silently has no effect on real syncs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.connectors import ConnectorSyncBody, connector_sync


def _make_connection():
    connection = MagicMock()
    connection.connection_id = "conn-1"
    connection.is_active = True
    return connection


def _make_connector():
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)
    connector.bucket_names = []
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "new-file-1", "modified_time": None},
                {"id": "changed-file-1", "modified_time": None},
            ],
            "next_page_token": None,
        }
    )
    return connector


@pytest.mark.asyncio
async def test_bucket_filter_sync_forwards_shared_to_new_and_changed_batches():
    body = ConnectorSyncBody(bucket_filter=["bucket-a"], shared=True)

    connector_service = MagicMock()
    connection = _make_connection()
    connector_service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    connector = _make_connector()
    connector_service.get_connector = AsyncMock(return_value=connector)
    connector_service.sync_specific_files = AsyncMock(side_effect=["task-new", "task-changed"])

    session_manager = MagicMock()
    user = MagicMock()
    user.jwt_token = "token"
    user.user_id = "user-1"

    with (
        patch(
            "api.connectors.get_synced_file_ids_for_connector",
            new=AsyncMock(return_value=(["changed-file-1"], [], "connector_file_id")),
        ),
        patch(
            "api.connectors.get_synced_id_to_modified_time_map",
            new=AsyncMock(return_value={"changed-file-1": 0.0}),
        ),
        patch(
            "api.connectors.classify_remote_file_change",
            side_effect=lambda fid, *_a, **_k: "new" if fid == "new-file-1" else "changed",
        ),
    ):
        response = await connector_sync(
            connector_type="ibm_cos",
            body=body,
            request=MagicMock(),
            connector_service=connector_service,
            session_manager=session_manager,
            user=user,
            session=AsyncMock(),
            rbac=MagicMock(),
        )

    assert response.status_code == 201
    assert connector_service.sync_specific_files.await_count == 2

    new_call, changed_call = connector_service.sync_specific_files.await_args_list
    assert new_call.args[2] == ["new-file-1"]
    assert new_call.kwargs["shared"] is True
    assert changed_call.args[2] == ["changed-file-1"]
    assert changed_call.kwargs["shared"] is True
