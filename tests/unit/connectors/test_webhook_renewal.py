"""Webhook subscription renewal.

Pins the periodic-renewal machinery: provider subscriptions are short-lived
(Google Drive channels ~24h, Microsoft Graph 3 days) and previously nothing
renewed them, so change notifications went silent days after connecting.

Covers `_parse_webhook_expiration`, `ConnectionManager.renew_expiring_
subscriptions` / `_renew_subscription` / `_persist_subscription_state`, and
the Graph PATCH `renew_subscription` on SharePoint/OneDrive.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


THRESHOLD = 12 * 3600


def _iso_in(hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# _parse_webhook_expiration
# ---------------------------------------------------------------------------


def test_parse_expiration_formats():
    from connectors.connection_manager import _parse_webhook_expiration as parse

    # ISO with offset
    assert parse("2026-06-14T12:00:00+00:00") == datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    # ISO with trailing Z
    assert parse("2026-06-14T12:00:00Z") == datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    # Graph 7-digit fractional seconds
    assert parse("2026-06-14T12:00:00.9356913Z") == datetime(
        2026, 6, 14, 12, 0, 0, 935691, tzinfo=UTC
    )
    # Naive ISO assumed UTC
    assert parse("2026-06-14T12:00:00").tzinfo is not None
    # Epoch-milliseconds (legacy raw Google Drive value), string and int
    epoch_ms = int(datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)
    assert parse(str(epoch_ms)) == datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    assert parse(epoch_ms) == datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    # Missing / garbage -> None (treated as unknown -> renew)
    assert parse(None) is None
    assert parse("") is None
    assert parse("not-a-date") is None


# ---------------------------------------------------------------------------
# renew_expiring_subscriptions / _renew_subscription
# ---------------------------------------------------------------------------


def _make_manager(tmp_path, connections):
    from connectors.connection_manager import ConnectionManager

    manager = ConnectionManager(connections_file=str(tmp_path / "connections.json"))
    manager.connections = {c.connection_id: c for c in connections}
    manager.save_connections = AsyncMock()
    return manager


def _make_connection(connection_id="conn-1", **config_overrides):
    from connectors.connection_manager import ConnectionConfig

    config = {
        "token_file": "token.json",
        "webhook_url": "https://api.example.com/connectors/google_drive/webhook",
        "webhook_channel_id": "old-channel",
        "subscription_id": "old-channel",
        "webhook_expiration": _iso_in(1),  # near expiry by default
    }
    config.update(config_overrides)
    config = {k: v for k, v in config.items() if v is not None}
    return ConnectionConfig(
        connection_id=connection_id,
        connector_type="google_drive",
        name="Test",
        config=config,
    )


def _make_connector(
    renew_result=None,
    setup_result="new-channel",
    resource_id="new-resource",
    expiration=None,
):
    connector = MagicMock()
    connector.renew_subscription = AsyncMock(return_value=renew_result)
    connector.cleanup_subscription = AsyncMock(return_value=True)
    connector.setup_subscription = AsyncMock(return_value=setup_result)
    connector.webhook_resource_id = resource_id
    connector.webhook_expiration = expiration or _iso_in(24)
    connector.cfg = MagicMock()
    connector.cfg.changes_page_token = "page-token-42"
    return connector


@pytest.mark.asyncio
async def test_healthy_subscription_is_skipped(tmp_path):
    connection = _make_connection(webhook_expiration=_iso_in(48))
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock()

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats == {"checked": 1, "renewed": 0, "failed": 0, "skipped": 1}
    manager.get_connector.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expiration",
    [_iso_in(1), _iso_in(-1), None],
    ids=["near-expiry", "expired", "unknown-expiry"],
)
async def test_near_expired_or_unknown_expiry_is_renewed(tmp_path, expiration):
    connection = _make_connection(webhook_expiration=expiration)
    connector = _make_connector()
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["renewed"] == 1


@pytest.mark.asyncio
async def test_missing_subscription_is_healed(tmp_path):
    """webhook_url set but no channel id (failed initial setup) -> recreated."""
    connection = _make_connection(
        webhook_channel_id=None, subscription_id=None, webhook_expiration=None
    )
    connector = _make_connector()
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["renewed"] == 1
    # No old subscription to extend or clean up
    connector.renew_subscription.assert_not_awaited()
    connector.cleanup_subscription.assert_not_awaited()
    connector.setup_subscription.assert_awaited_once()
    assert connection.config["webhook_channel_id"] == "new-channel"


@pytest.mark.asyncio
async def test_legacy_subscription_id_is_renewed(tmp_path):
    """Legacy configs may only have subscription_id; renew that id instead of duplicating."""
    new_expiration = _iso_in(72)
    connection = _make_connection(
        webhook_channel_id=None,
        subscription_id="legacy-subscription",
        webhook_expiration=_iso_in(1),
    )
    connector = _make_connector(renew_result=new_expiration)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["renewed"] == 1
    connector.renew_subscription.assert_awaited_once_with("legacy-subscription")
    connector.cleanup_subscription.assert_not_awaited()
    connector.setup_subscription.assert_not_awaited()
    assert connection.config["webhook_expiration"] == new_expiration


@pytest.mark.asyncio
async def test_connection_without_webhook_url_is_ignored(tmp_path):
    connection = _make_connection(webhook_url=None)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock()

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats == {"checked": 0, "renewed": 0, "failed": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_inactive_connection_is_ignored(tmp_path):
    connection = _make_connection()
    connection.is_active = False
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock()

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["checked"] == 0


@pytest.mark.asyncio
async def test_auth_failure_leaves_config_untouched(tmp_path):
    connection = _make_connection()
    original_config = dict(connection.config)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=None)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["failed"] == 1
    assert connection.config == original_config
    manager.save_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_inplace_extension_skips_recreate(tmp_path):
    """Graph PATCH success: only the expiration is updated, no delete+create."""
    new_expiration = _iso_in(72)
    connection = _make_connection()
    connector = _make_connector(renew_result=new_expiration)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["renewed"] == 1
    connector.renew_subscription.assert_awaited_once_with("old-channel")
    connector.cleanup_subscription.assert_not_awaited()
    connector.setup_subscription.assert_not_awaited()
    assert connection.config["webhook_expiration"] == new_expiration
    assert connection.config["webhook_channel_id"] == "old-channel"  # unchanged
    manager.save_connections.assert_awaited()


@pytest.mark.asyncio
async def test_recreate_path_cleans_up_and_persists(tmp_path):
    """No in-place renewal (Google Drive): stop old channel, create new one,
    persist new ids + expiration + changes page token."""
    new_expiration = _iso_in(24)
    connection = _make_connection()
    connector = _make_connector(renew_result=None, expiration=new_expiration)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["renewed"] == 1
    connector.cleanup_subscription.assert_awaited_once_with("old-channel")
    connector.setup_subscription.assert_awaited_once()
    cfg = connection.config
    assert cfg["webhook_channel_id"] == "new-channel"
    assert cfg["subscription_id"] == "new-channel"
    assert cfg["resource_id"] == "new-resource"
    assert cfg["webhook_expiration"] == new_expiration
    assert cfg["changes_page_token"] == "page-token-42"
    manager.save_connections.assert_awaited()


@pytest.mark.asyncio
async def test_recreate_skips_setup_when_cleanup_returns_false(tmp_path):
    """Avoid duplicate/leaked provider webhooks when the old one cannot be stopped."""
    connection = _make_connection()
    connector = _make_connector(renew_result=None)
    connector.cleanup_subscription = AsyncMock(return_value=False)
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["failed"] == 1
    connector.cleanup_subscription.assert_awaited_once_with("old-channel")
    connector.setup_subscription.assert_not_awaited()
    assert connection.config["webhook_channel_id"] == "old-channel"


@pytest.mark.asyncio
async def test_recreate_skips_setup_when_cleanup_raises(tmp_path):
    connection = _make_connection()
    connector = _make_connector(renew_result=None)
    connector.cleanup_subscription = AsyncMock(side_effect=RuntimeError("missing resource id"))
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["failed"] == 1
    connector.cleanup_subscription.assert_awaited_once_with("old-channel")
    connector.setup_subscription.assert_not_awaited()
    assert connection.config["webhook_channel_id"] == "old-channel"


@pytest.mark.asyncio
async def test_no_webhook_configured_sentinel_counts_as_failure(tmp_path):
    connection = _make_connection()
    connector = _make_connector(renew_result=None, setup_result="no-webhook-configured")
    manager = _make_manager(tmp_path, [connection])
    manager.get_connector = AsyncMock(return_value=connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["failed"] == 1
    # Old channel id never cleared on failure
    assert connection.config["webhook_channel_id"] == "old-channel"


@pytest.mark.asyncio
async def test_one_failing_connection_does_not_block_others(tmp_path):
    bad = _make_connection(connection_id="bad")
    good = _make_connection(connection_id="good")
    good_connector = _make_connector()
    manager = _make_manager(tmp_path, [bad, good])

    async def _get_connector(connection_id):
        if connection_id == "bad":
            raise RuntimeError("boom")
        return good_connector

    manager.get_connector = AsyncMock(side_effect=_get_connector)

    stats = await manager.renew_expiring_subscriptions(THRESHOLD)

    assert stats["failed"] == 1
    assert stats["renewed"] == 1


# ---------------------------------------------------------------------------
# SharePoint / OneDrive — Graph PATCH renew_subscription
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakePatchClient:
    def __init__(self, captured: dict, response: _FakeResponse):
        self._captured = captured
        self._response = response

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def patch(self, url, json=None, headers=None, timeout=None):
        self._captured["url"] = url
        self._captured["json"] = json
        return self._response


class _FakeOAuth:
    def get_access_token(self) -> str:
        return "access-token"


GRAPH_CONNECTORS = [
    ("connectors.sharepoint.connector", "SharePointConnector"),
    ("connectors.onedrive.connector", "OneDriveConnector"),
]


def _graph_connector(module_path: str, cls_name: str, tmp_path):
    import importlib

    cls = getattr(importlib.import_module(module_path), cls_name)
    connector = cls({"token_file": str(tmp_path / "token.json")})
    connector.authenticate = AsyncMock(return_value=True)
    connector.oauth = _FakeOAuth()
    return connector


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name", GRAPH_CONNECTORS)
async def test_graph_renew_patches_subscription(tmp_path, monkeypatch, module_path, cls_name):
    import httpx

    connector = _graph_connector(module_path, cls_name, tmp_path)
    captured = {}
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _FakePatchClient(
            captured, _FakeResponse(200, {"expirationDateTime": "2026-06-17T00:00:00Z"})
        ),
    )

    expiration = await connector.renew_subscription("sub-123")

    assert expiration == "2026-06-17T00:00:00Z"
    assert connector.webhook_expiration == "2026-06-17T00:00:00Z"
    assert captured["url"].endswith("/subscriptions/sub-123")
    assert "expirationDateTime" in captured["json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name", GRAPH_CONNECTORS)
async def test_graph_renew_returns_none_on_404(tmp_path, monkeypatch, module_path, cls_name):
    import httpx

    connector = _graph_connector(module_path, cls_name, tmp_path)
    monkeypatch.setattr(httpx, "AsyncClient", _FakePatchClient({}, _FakeResponse(404)))

    assert await connector.renew_subscription("sub-123") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name", GRAPH_CONNECTORS)
async def test_graph_renew_sentinel_skips_http(tmp_path, module_path, cls_name):
    connector = _graph_connector(module_path, cls_name, tmp_path)
    connector.authenticate = AsyncMock(side_effect=AssertionError("must not authenticate"))

    assert await connector.renew_subscription("no-webhook-configured") is None


@pytest.mark.asyncio
async def test_google_drive_has_no_inplace_renewal(tmp_path):
    """Drive inherits the base hook: None -> caller recreates the channel."""
    from connectors.google_drive.connector import GoogleDriveConfig, GoogleDriveConnector

    connector = GoogleDriveConnector.__new__(GoogleDriveConnector)
    connector.cfg = GoogleDriveConfig(
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        token_file="/tmp/fake-token.json",
    )

    assert await connector.renew_subscription("channel-1") is None
