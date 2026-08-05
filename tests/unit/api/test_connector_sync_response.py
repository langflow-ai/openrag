"""Unit test for connector_sync response reporting (GitHub issue #1547).

The success response must report exactly 1 connection synced and a singular message,
even when multiple active connections exist, because the function dispatches exactly
one task from exactly one working connection.
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


def _json(response):
    return json.loads(response.body.decode())


@pytest.mark.asyncio
async def test_connector_sync_reports_one_connection_with_multiple_active(monkeypatch):
    """When multiple active connections exist, response should report 1 connection synced."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["file-a", "file-b"], [], "document_id")),
    )
    monkeypatch.setattr(
        connectors_api,
        "reconcile_orphans_for_connector_type",
        AsyncMock(return_value=[]),
    )

    # Create THREE active connections to test the over-counting bug
    conn1 = _make_connection("conn-1")
    conn2 = _make_connection("conn-2")
    conn3 = _make_connection("conn-3")

    # First connector authenticates successfully (will be selected as working_connection)
    connector1 = MagicMock()
    connector1.authenticate = AsyncMock(return_value=True)

    # Other connectors don't matter since first one succeeds
    connector2 = MagicMock()
    connector2.authenticate = AsyncMock(return_value=False)
    connector3 = MagicMock()
    connector3.authenticate = AsyncMock(return_value=False)

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[conn1, conn2, conn3])

    async def _get_connector(connection_id):
        return {
            "conn-1": connector1,
            "conn-2": connector2,
            "conn-3": connector3,
        }[connection_id]

    service.get_connector = AsyncMock(side_effect=_get_connector)
    service.sync_specific_files = AsyncMock(return_value="task-123")

    response = await connectors_api.connector_sync(
        "google_drive",
        connectors_api.ConnectorSyncBody(),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    body = _json(response)

    # The fix: should report 1 connection synced, not 3
    assert body["connections_synced"] == 1, (
        f"Expected connections_synced=1 but got {body['connections_synced']}. "
        "Only one connection is actually synced even when multiple are active."
    )

    # The fix: message should be singular, not plural
    assert body["message"] == "Started syncing files from 1 google_drive connection", (
        f"Expected singular message but got: {body['message']}"
    )

    # Verify exactly one task was dispatched
    assert body["task_ids"] == ["task-123"]
    assert len(body["task_ids"]) == 1

    # Verify only the first connector was used
    service.sync_specific_files.assert_awaited_once()
    args = service.sync_specific_files.await_args.args
    assert args[0] == "conn-1"  # connection_id of first connector


def _preview_service_with_working_connection():
    """Service mock whose single active connection authenticates and syncs."""
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=[_make_connection("c1")])
    service.get_connector = AsyncMock(return_value=connector)
    service.sync_specific_files = AsyncMock(return_value="task-preview")
    return service


@pytest.mark.asyncio
async def test_connector_sync_passes_preview_mode_to_sync_specific_files(monkeypatch):
    """body.preview=True threads preview_mode=True into sync_specific_files (OSS/SaaS)."""
    from api import connectors as connectors_api
    from api import documents as documents_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "is_ingest_preview_enabled", lambda: True)
    monkeypatch.setattr(documents_api, "_ensure_index_exists", AsyncMock())

    service = _preview_service_with_working_connection()

    response = await connectors_api.connector_sync(
        "google_drive",
        connectors_api.ConnectorSyncBody(selected_files=["file-a"], preview=True),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    assert service.sync_specific_files.await_args.kwargs["preview_mode"] is True


@pytest.mark.asyncio
async def test_connector_sync_ignores_preview_when_disabled(monkeypatch):
    """body.preview=True is ignored (preview_mode=False) when the run mode disables preview."""
    from api import connectors as connectors_api
    from api import documents as documents_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "is_ingest_preview_enabled", lambda: False)
    monkeypatch.setattr(documents_api, "_ensure_index_exists", AsyncMock())

    service = _preview_service_with_working_connection()

    response = await connectors_api.connector_sync(
        "google_drive",
        connectors_api.ConnectorSyncBody(selected_files=["file-a"], preview=True),
        request=MagicMock(),
        connector_service=service,
        session_manager=MagicMock(),
        user=SimpleNamespace(user_id="alice", jwt_token="token"),
        session=MagicMock(),
    )

    assert response.status_code == 201
    service.sync_specific_files.assert_awaited_once()
    assert service.sync_specific_files.await_args.kwargs["preview_mode"] is False
