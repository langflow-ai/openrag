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
from datetime import UTC
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
        self.query_params: dict[str, str] = {}

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
# SharePoint/OneDrive handle_webhook — delta query for changed files
# ---------------------------------------------------------------------------


GRAPH_CONNECTORS = [
    ("connectors.sharepoint.connector", "SharePointConnector", "sharepoint"),
    ("connectors.onedrive.connector", "OneDriveConnector", "onedrive"),
]


class _FakeOAuth:
    def get_access_token(self) -> str:
        return "access-token"


def _graph_connector(module_path: str, cls_name: str, tmp_path, webhook_url: str | None):
    import importlib

    cls = getattr(importlib.import_module(module_path), cls_name)
    config = {"token_file": str(tmp_path / "token.json")}
    if webhook_url:
        config["webhook_url"] = webhook_url
    connector = cls(config)
    connector.authenticate = AsyncMock(return_value=True)
    connector.oauth = _FakeOAuth()
    return connector


class _FakeDeltaClient:
    """Stands in for httpx.AsyncClient; serves Graph delta GET responses."""

    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.requested_urls: list[str] = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, timeout=None):
        self.requested_urls.append(url)

        class _Resp:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        return _Resp(self._pages[len(self.requested_urls) - 1])


GRAPH_NOTIFICATION = {"value": [{"resource": "me/drive/root", "changeType": "updated"}]}


def _recent_iso():
    from datetime import datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name,connector_type", GRAPH_CONNECTORS)
async def test_graph_webhook_runs_delta_query(
    tmp_path, monkeypatch, module_path, cls_name, connector_type
):
    """Graph notifications don't name the changed items; the connector must
    discover them via a drive delta query."""
    import httpx

    connector = _graph_connector(module_path, cls_name, tmp_path, webhook_url=None)

    delta_page = {
        "value": [
            {"id": "file-recent", "file": {}, "lastModifiedDateTime": _recent_iso()},
            {"id": "file-old", "file": {}, "lastModifiedDateTime": "2020-01-01T00:00:00Z"},
            {"id": "folder-1", "folder": {}, "lastModifiedDateTime": _recent_iso()},
            {"id": "file-gone", "deleted": {}},
            {"id": "folder-gone", "folder": {}, "deleted": {}},
        ],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=abc",
    }
    fake_client = _FakeDeltaClient([delta_page])
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    affected = await connector.handle_webhook(GRAPH_NOTIFICATION)

    # First sweep: recently-modified files count regardless of the cutoff applied
    # to live files; deleted files propagate so indexed chunks get cleaned up,
    # deleted folders don't.
    assert affected == ["file-recent", "file-gone"]
    assert connector._delta_link == "https://graph.microsoft.com/v1.0/delta?token=abc"
    assert fake_client.requested_urls[0].endswith("/delta")


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name,connector_type", GRAPH_CONNECTORS)
async def test_graph_webhook_uses_stored_delta_link(
    tmp_path, monkeypatch, module_path, cls_name, connector_type
):
    import httpx

    connector = _graph_connector(module_path, cls_name, tmp_path, webhook_url=None)
    connector._delta_link = "https://graph.microsoft.com/v1.0/delta?token=prev"

    delta_page = {
        # With a delta link the results ARE the changes — no recency filter.
        "value": [{"id": "file-old", "file": {}, "lastModifiedDateTime": "2020-01-01T00:00:00Z"}],
        "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=next",
    }
    fake_client = _FakeDeltaClient([delta_page])
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    affected = await connector.handle_webhook(GRAPH_NOTIFICATION)

    assert affected == ["file-old"]
    assert fake_client.requested_urls == ["https://graph.microsoft.com/v1.0/delta?token=prev"]
    assert connector._delta_link == "https://graph.microsoft.com/v1.0/delta?token=next"


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name,connector_type", GRAPH_CONNECTORS)
async def test_graph_webhook_empty_payload_skips_delta(
    tmp_path, module_path, cls_name, connector_type
):
    connector = _graph_connector(module_path, cls_name, tmp_path, webhook_url=None)

    assert await connector.handle_webhook({"value": []}) == []
    connector.authenticate.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_data_source_auth — subscription registration on connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_source_auth_registers_webhook_subscription():
    """Data-source connections don't go through update_connection, so the OAuth
    callback must register the change-notification subscription itself."""
    from services.auth_service import AuthService

    manager = MagicMock()
    connector = MagicMock()
    manager.get_connector = AsyncMock(return_value=connector)
    manager._setup_webhook_if_needed = AsyncMock()

    connector_service = MagicMock()
    connector_service.connection_manager = manager
    service = AuthService(session_manager=MagicMock(), connector_service=connector_service)

    connection_config = MagicMock()
    connection_config.connector_type = "google_drive"

    result = await service._handle_data_source_auth("conn-1", connection_config)

    assert result["status"] == "authenticated"
    manager._setup_webhook_if_needed.assert_awaited_once_with(
        "conn-1", connection_config, connector
    )


@pytest.mark.asyncio
async def test_data_source_auth_survives_subscription_failure():
    """Webhook registration failure must not fail the OAuth connect itself."""
    from services.auth_service import AuthService

    manager = MagicMock()
    manager.get_connector = AsyncMock(return_value=MagicMock())
    manager._setup_webhook_if_needed = AsyncMock(side_effect=RuntimeError("graph down"))

    connector_service = MagicMock()
    connector_service.connection_manager = manager
    service = AuthService(session_manager=MagicMock(), connector_service=connector_service)

    connection_config = MagicMock()
    connection_config.connector_type = "google_drive"

    result = await service._handle_data_source_auth("conn-1", connection_config)

    assert result["status"] == "authenticated"


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
