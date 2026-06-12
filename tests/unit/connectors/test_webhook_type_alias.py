"""Webhook endpoint legacy-type aliasing and channel lookup resilience.

Pins the fix for SaaS Google Drive push notifications being silently dropped:
watches registered via the legacy ``GOOGLE_DRIVE_WEBHOOK_URL`` override pointed
at ``/connectors/google/webhook`` (connector type ``google``, which doesn't
exist), so every notification died with "Unknown connector type: google".
``connector_webhook`` now aliases ``google`` -> ``google_drive``.

Also pins ``get_connection_by_webhook_id`` re-reading the persisted store when
a channel id is missing from the in-memory dict (subscription created by
another replica or before a restart).
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.method = "POST"
        self.headers = headers
        self.query_params = {}

    async def json(self):
        return {}

    async def body(self):
        return b"{}"


class _FakeDriveConnector:
    """Stands in for the temp GoogleDriveConnector used by the webhook route."""

    def handle_webhook_validation(self, method, headers, query_params):
        return None

    def extract_webhook_channel_id(self, payload, headers):
        normalized = {k.lower(): v for k, v in headers.items()}
        return normalized.get("x-goog-channel-id")


def _webhook_service(channel_id: str, connection):
    """connector_service mock wired so a matching channel resolves `connection`."""
    service = MagicMock()
    service.connection_manager._create_connector = MagicMock(return_value=_FakeDriveConnector())
    service.connection_manager.get_connection_by_webhook_id = AsyncMock(
        side_effect=lambda cid: connection if cid == channel_id else None
    )
    handler = MagicMock()
    handler.handle_webhook = AsyncMock(return_value=[])
    service._get_connector = AsyncMock(return_value=handler)
    return service


@pytest.fixture(autouse=True)
def _quiet_endpoint(monkeypatch):
    import api.connectors as api_connectors

    monkeypatch.setattr(api_connectors.TelemetryClient, "send_event", AsyncMock(return_value=None))
    monkeypatch.setattr(api_connectors, "is_connector_access_policy_enforced", lambda: False)


# ---------------------------------------------------------------------------
# connector_webhook — legacy type aliasing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path_type", ["google", "google_drive"])
async def test_webhook_accepts_legacy_google_type(path_type):
    from api.connectors import connector_webhook

    connection = MagicMock()
    connection.connection_id = "conn-1"
    connection.user_id = "user-1"
    connection.is_active = True

    service = _webhook_service("chan-1", connection)
    session_manager = MagicMock()
    session_manager.get_user = MagicMock(return_value=None)

    request = _FakeRequest({"content-type": "application/json", "x-goog-channel-id": "chan-1"})
    response = await connector_webhook(
        path_type,
        request,
        connector_service=service,
        session_manager=session_manager,
        session=MagicMock(),
    )

    body = json.loads(response.body)
    assert body["status"] == "processed"
    # The legacy path segment must be normalized before any connector lookup.
    assert body["connector_type"] == "google_drive"
    assert body["connection_id"] == "conn-1"


@pytest.mark.asyncio
async def test_webhook_sync_replaces_existing_files():
    """A webhook fires because the file changed, so the triggered sync must
    replace the indexed copy instead of failing the duplicate-filename guard."""
    from api.connectors import connector_webhook

    connection = MagicMock()
    connection.connection_id = "conn-1"
    connection.user_id = "user-1"
    connection.is_active = True

    service = _webhook_service("chan-1", connection)
    handler = MagicMock()
    handler.handle_webhook = AsyncMock(return_value=["file-1"])
    service._get_connector = AsyncMock(return_value=handler)
    service.sync_specific_files = AsyncMock(return_value="task-1")

    request = _FakeRequest({"content-type": "application/json", "x-goog-channel-id": "chan-1"})
    response = await connector_webhook(
        "google_drive",
        request,
        connector_service=service,
        session_manager=MagicMock(),
        session=MagicMock(),
    )

    body = json.loads(response.body)
    assert body["status"] == "processed"
    assert body["task_id"] == "task-1"
    sync_kwargs = service.sync_specific_files.await_args.kwargs
    assert sync_kwargs["replace_duplicates"] is True


@pytest.mark.asyncio
async def test_webhook_unknown_type_is_ignored_not_500():
    from api.connectors import connector_webhook

    service = MagicMock()
    service.connection_manager._create_connector = MagicMock(
        side_effect=ValueError("Unknown connector type: box2")
    )

    request = _FakeRequest({"content-type": "application/json"})
    response = await connector_webhook(
        "box2",
        request,
        connector_service=service,
        session_manager=MagicMock(),
        session=MagicMock(),
    )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {"status": "ignored", "reason": "no_channel_id"}


# ---------------------------------------------------------------------------
# get_connection_by_webhook_id — reload-from-disk fallback
# ---------------------------------------------------------------------------


def _write_connections_file(path: Path, channel_id: str):
    path.write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "connection_id": "conn-disk",
                        "connector_type": "google_drive",
                        "name": "drive",
                        "config": {"webhook_channel_id": channel_id},
                        "user_id": "user-1",
                        "created_at": "2026-06-12T16:00:00",
                        "is_active": True,
                    }
                ]
            }
        )
    )


@pytest.mark.asyncio
async def test_webhook_lookup_reloads_persisted_store(tmp_path):
    from connectors.connection_manager import ConnectionManager

    connections_file = tmp_path / "connections.json"
    _write_connections_file(connections_file, "chan-disk")

    # Fresh manager that has NOT loaded the file (e.g. channel registered by
    # another replica after this one started).
    manager = ConnectionManager(connections_file=str(connections_file))
    assert manager.connections == {}

    connection = await manager.get_connection_by_webhook_id("chan-disk")

    assert connection is not None
    assert connection.connection_id == "conn-disk"


@pytest.mark.asyncio
async def test_webhook_lookup_returns_none_for_unknown_channel(tmp_path):
    from connectors.connection_manager import ConnectionManager

    connections_file = tmp_path / "connections.json"
    _write_connections_file(connections_file, "chan-disk")

    manager = ConnectionManager(connections_file=str(connections_file))

    assert await manager.get_connection_by_webhook_id("chan-other") is None
