"""Webhook subscription URL correctness for all connectors.

Pins the fix for the doubled Microsoft Graph notificationUrl: the connection
config's ``webhook_url`` is already the full endpoint
(``{WEBHOOK_BASE_URL}/connectors/<type>/webhook``, set at connect time in
auth_service), so SharePoint/OneDrive must pass it to Graph verbatim. They
previously appended ``/webhook/<type>``, producing a URL with no registered
route — Graph's synchronous validation probe got a 404 and subscription
creation always failed.

Also pins Google Drive's webhook address resolution order
(config ``webhook_url`` → ``GOOGLE_DRIVE_WEBHOOK_URL`` setting →
``WEBHOOK_BASE_URL`` + path) and the AWS S3 no-op stubs.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; captures the Graph subscription POST."""

    def __init__(self, captured: dict):
        self._captured = captured

    def __call__(self, *args, **kwargs):
        # Connector code instantiates httpx.AsyncClient(); return ourselves.
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self._captured["url"] = url
        self._captured["json"] = json
        return _FakeResponse({"id": "sub-123", "expirationDateTime": "2026-06-14T00:00:00Z"})


class _FakeOAuth:
    def get_access_token(self) -> str:
        return "access-token"


GRAPH_CONNECTORS = [
    ("connectors.sharepoint.connector", "SharePointConnector", "sharepoint"),
    ("connectors.onedrive.connector", "OneDriveConnector", "onedrive"),
]


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


# ---------------------------------------------------------------------------
# SharePoint / OneDrive — Graph notificationUrl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name,connector_type", GRAPH_CONNECTORS)
async def test_graph_notification_url_is_config_webhook_url_verbatim(
    tmp_path, monkeypatch, module_path, cls_name, connector_type
):
    import httpx

    webhook_url = f"https://api.example.com/connectors/{connector_type}/webhook"
    connector = _graph_connector(module_path, cls_name, tmp_path, webhook_url)

    captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient(captured))

    subscription_id = await connector.setup_subscription()

    assert subscription_id == "sub-123"
    assert captured["url"].endswith("/subscriptions")
    body = captured["json"]
    assert body["notificationUrl"] == webhook_url
    # Regression: must not re-append a /webhook/<type> segment to the
    # already-complete endpoint (yields a 404 route, Graph rejects it).
    assert f"/webhook/{connector_type}" not in body["notificationUrl"]
    # The Graph-reported expiration is exposed for persistence/renewal
    assert connector.webhook_expiration == "2026-06-14T00:00:00Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path,cls_name,connector_type", GRAPH_CONNECTORS)
async def test_graph_subscription_skipped_without_webhook_url(
    tmp_path, module_path, cls_name, connector_type
):
    connector = _graph_connector(module_path, cls_name, tmp_path, webhook_url=None)

    assert await connector.setup_subscription() == "no-webhook-configured"
    connector.authenticate.assert_not_awaited()


# ---------------------------------------------------------------------------
# Google Drive — _resolve_webhook_address resolution order
# ---------------------------------------------------------------------------


def _gdrive_connector(config: dict):
    """Build a minimal GoogleDriveConnector via __new__ (no real credentials)."""
    from connectors.google_drive.connector import GoogleDriveConfig, GoogleDriveConnector

    connector = GoogleDriveConnector.__new__(GoogleDriveConnector)
    connector.config = config
    connector.cfg = GoogleDriveConfig(
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        token_file="/tmp/fake-token.json",
    )
    return connector


def _set_webhook_settings(monkeypatch, legacy: str | None, base: str | None):
    import config.settings as settings

    monkeypatch.setattr(settings, "GOOGLE_DRIVE_WEBHOOK_URL", legacy)
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", base)


def test_google_drive_config_webhook_url_wins(monkeypatch):
    _set_webhook_settings(
        monkeypatch, "https://legacy.example.com/hook", "https://base.example.com"
    )
    connector = _gdrive_connector(
        {"webhook_url": " https://api.example.com/connectors/google_drive/webhook "}
    )

    assert (
        connector._resolve_webhook_address()
        == "https://api.example.com/connectors/google_drive/webhook"
    )


def test_google_drive_legacy_setting_overrides_base_url(monkeypatch):
    _set_webhook_settings(
        monkeypatch, "https://legacy.example.com/hook", "https://base.example.com"
    )
    connector = _gdrive_connector({})

    assert connector._resolve_webhook_address() == "https://legacy.example.com/hook"


def test_google_drive_falls_back_to_webhook_base_url(monkeypatch):
    _set_webhook_settings(monkeypatch, None, "https://base.example.com/")
    connector = _gdrive_connector({})

    assert (
        connector._resolve_webhook_address()
        == "https://base.example.com/connectors/google_drive/webhook"
    )


def test_google_drive_returns_none_when_nothing_configured(monkeypatch):
    _set_webhook_settings(monkeypatch, None, None)
    connector = _gdrive_connector({})

    assert connector._resolve_webhook_address() is None


# ---------------------------------------------------------------------------
# AWS S3 — subscriptions are explicit no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aws_s3_subscription_is_noop():
    from connectors.aws_s3.connector import S3Connector

    connector = S3Connector({"bucket_names": ["bucket"]})

    assert await connector.setup_subscription() == ""
    assert await connector.cleanup_subscription("") is True
    assert connector.extract_webhook_channel_id({}, {}) is None
    assert await connector.handle_webhook({"value": []}) == []
