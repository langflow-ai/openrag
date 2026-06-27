"""Unit tests for the Azure Blob Storage connector.

Covers credential resolution (both auth modes + env fallback), client-factory
validation, file listing (prefix filter, dir-marker skip, max_files), composite
file-id round-trip, blob download → ConnectorDocument mapping (owner-based DLS),
authenticate success/failure, IBM_AUTH_ENABLED gating, config-builder validation,
and the webhook stubs.

The sync azure-storage-blob client is replaced with a MagicMock — the connector
offloads it via asyncio.to_thread, so plain mocks work without async machinery.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancements.connectors.azure_blob import auth as az_auth  # noqa: E402
from enhancements.connectors.azure_blob import connector as az_connector  # noqa: E402
from enhancements.connectors.azure_blob.connector import (  # noqa: E402
    AzureBlobConnector,
    _make_file_id,
    _split_file_id,
)
from enhancements.connectors.azure_blob.models import AzureBlobConfigureBody  # noqa: E402
from enhancements.connectors.azure_blob.support import build_azure_blob_config  # noqa: E402

CONN_STR = "AZURE_STORAGE_CONNECTION_STRING"
ACCT_NAME = "AZURE_STORAGE_ACCOUNT_NAME"
ACCT_KEY = "AZURE_STORAGE_ACCOUNT_KEY"
ENDPOINT = "AZURE_STORAGE_ENDPOINT"


def _clear_azure_env(monkeypatch):
    for var in (CONN_STR, ACCT_NAME, ACCT_KEY, ENDPOINT):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Composite file-id helpers
# ---------------------------------------------------------------------------


def test_make_and_split_file_id_roundtrip():
    file_id = _make_file_id("mycontainer", "path/to/blob.pdf")
    assert file_id == "mycontainer::path/to/blob.pdf"
    container, blob = _split_file_id(file_id)
    assert container == "mycontainer"
    assert blob == "path/to/blob.pdf"


def test_split_file_id_invalid_raises():
    with pytest.raises(ValueError):
        _split_file_id("no-separator-here")


def test_split_file_id_blob_with_separator_only_splits_once():
    container, blob = _split_file_id("c::a::b")
    assert container == "c"
    assert blob == "a::b"


# ---------------------------------------------------------------------------
# Credential resolution + client factory
# ---------------------------------------------------------------------------


def test_resolve_credentials_prefers_config_over_env(monkeypatch):
    _clear_azure_env(monkeypatch)
    monkeypatch.setenv(CONN_STR, "env-conn-str")
    creds = az_auth._resolve_credentials({"connection_string": "cfg-conn-str"})
    assert creds["connection_string"] == "cfg-conn-str"


def test_resolve_credentials_env_fallback(monkeypatch):
    _clear_azure_env(monkeypatch)
    monkeypatch.setenv(ACCT_NAME, "acct")
    monkeypatch.setenv(ACCT_KEY, "key")
    monkeypatch.setenv(ENDPOINT, "http://127.0.0.1:10000/devstoreaccount1")
    creds = az_auth._resolve_credentials({"auth_mode": "account_key"})
    assert creds["account_name"] == "acct"
    assert creds["account_key"] == "key"
    assert creds["endpoint_url"] == "http://127.0.0.1:10000/devstoreaccount1"


def test_create_client_connection_string_mode(monkeypatch):
    _clear_azure_env(monkeypatch)
    # Azurite dev shortcut constructs fully offline.
    client = az_auth.create_blob_service_client(
        {"auth_mode": "connection_string", "connection_string": "UseDevelopmentStorage=true"}
    )
    assert client is not None


def test_create_client_account_key_mode_with_endpoint(monkeypatch):
    _clear_azure_env(monkeypatch)
    client = az_auth.create_blob_service_client(
        {
            "auth_mode": "account_key",
            "account_name": "devstoreaccount1",
            "account_key": "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT==",
            "endpoint_url": "http://127.0.0.1:10000/devstoreaccount1",
        }
    )
    assert client is not None


def test_create_client_connection_string_missing_raises(monkeypatch):
    _clear_azure_env(monkeypatch)
    with pytest.raises(ValueError, match="Connection string mode requires"):
        az_auth.create_blob_service_client({"auth_mode": "connection_string"})


def test_create_client_account_key_missing_raises(monkeypatch):
    _clear_azure_env(monkeypatch)
    with pytest.raises(ValueError, match="Account key mode requires"):
        az_auth.create_blob_service_client({"auth_mode": "account_key", "account_name": "acct"})


# ---------------------------------------------------------------------------
# Account-name resolution (used by get_client_id / status checks)
# ---------------------------------------------------------------------------


def test_account_name_from_connection_string_dev_storage():
    assert az_auth._account_name_from_connection_string("UseDevelopmentStorage=true") == (
        "devstoreaccount1"
    )


def test_account_name_from_connection_string_account_name():
    conn = "DefaultEndpointsProtocol=https;AccountName=myacct;AccountKey=ab==;EndpointSuffix=x"
    assert az_auth._account_name_from_connection_string(conn) == "myacct"


def test_account_name_from_connection_string_sas_host_style():
    conn = "BlobEndpoint=https://myacct.blob.core.windows.net;SharedAccessSignature=sv=2021"
    assert az_auth._account_name_from_connection_string(conn) == "myacct"


def test_account_name_from_connection_string_sas_path_style():
    conn = "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;SharedAccessSignature=sv=x"
    assert az_auth._account_name_from_connection_string(conn) == "devstoreaccount1"


def test_account_name_from_connection_string_unparseable_returns_none():
    assert az_auth._account_name_from_connection_string("SharedAccessSignature=sv=2021") is None


def test_account_name_from_config_prefers_account_name(monkeypatch):
    _clear_azure_env(monkeypatch)
    assert az_auth.account_name_from_config({"account_name": "explicit"}) == "explicit"


def test_account_name_from_config_parses_connection_string(monkeypatch):
    _clear_azure_env(monkeypatch)
    cfg = {"auth_mode": "connection_string", "connection_string": "UseDevelopmentStorage=true"}
    assert az_auth.account_name_from_config(cfg) == "devstoreaccount1"


def test_get_client_id_connection_string_mode_does_not_raise(monkeypatch):
    """Regression: connection-string mode (Azurite) must yield a stable id, not raise.

    Otherwise the status endpoint marks an authenticated connection as
    unauthenticated and the UI keeps showing "Connect".
    """
    _clear_azure_env(monkeypatch)
    connector = AzureBlobConnector(
        {"auth_mode": "connection_string", "connection_string": "UseDevelopmentStorage=true"}
    )
    assert connector.get_client_id() == "devstoreaccount1"


def test_get_client_id_account_key_mode(monkeypatch):
    _clear_azure_env(monkeypatch)
    connector = AzureBlobConnector(
        {"auth_mode": "account_key", "account_name": "acct", "account_key": "k"}
    )
    assert connector.get_client_id() == "acct"


def test_get_client_id_no_credentials_raises(monkeypatch):
    _clear_azure_env(monkeypatch)
    connector = AzureBlobConnector({"auth_mode": "account_key"})
    with pytest.raises(ValueError, match="Azure Blob credentials not set"):
        connector.get_client_id()


# ---------------------------------------------------------------------------
# is_available gating (IBM_AUTH_ENABLED / OPENRAG_DEV_AZURE_BLOB)
# ---------------------------------------------------------------------------


def test_is_available_gated_on_ibm_auth_enabled(monkeypatch):
    monkeypatch.setattr(az_connector, "IBM_AUTH_ENABLED", True)
    monkeypatch.setattr(az_connector, "is_dev_azure_blob_enabled", lambda: False)
    assert AzureBlobConnector.is_available(MagicMock()) is True
    monkeypatch.setattr(az_connector, "IBM_AUTH_ENABLED", False)
    assert AzureBlobConnector.is_available(MagicMock()) is False


def test_is_available_dev_flag_bypasses_ibm_auth(monkeypatch):
    monkeypatch.setattr(az_connector, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(az_connector, "is_dev_azure_blob_enabled", lambda: True)
    assert AzureBlobConnector.is_available(MagicMock()) is True


# ---------------------------------------------------------------------------
# Fake Azure client helpers
# ---------------------------------------------------------------------------


def _blob(name, size=10, modified=None):
    b = MagicMock()
    b.name = name
    b.size = size
    b.last_modified = modified
    return b


def _make_fake_client(containers):
    """containers: dict[name -> list[blob]]."""
    client = MagicMock()
    # NB: MagicMock(name=...) sets the mock's repr name, not a .name attribute,
    # so build the container mocks and assign .name explicitly.
    container_mocks = []
    for cname in containers:
        cm = MagicMock()
        cm.name = cname
        container_mocks.append(cm)
    client.list_containers.return_value = container_mocks

    def _get_container_client(name):
        cc = MagicMock()

        def _list_blobs(name_starts_with=None):
            blobs = containers[name]
            if name_starts_with:
                blobs = [b for b in blobs if b.name.startswith(name_starts_with)]
            return iter(blobs)

        cc.list_blobs.side_effect = _list_blobs
        return cc

    client.get_container_client.side_effect = _get_container_client
    return client


@pytest.fixture
def patched_factory():
    """Patch create_blob_service_client in the connector module; yield a setter."""
    with patch.object(az_connector, "create_blob_service_client") as factory:
        yield factory


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_files_single_container(patched_factory):
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    patched_factory.return_value = _make_fake_client(
        {"docs": [_blob("a.pdf", 5, ts), _blob("b.txt", 7, ts)]}
    )
    conn = AzureBlobConnector({"container_names": ["docs"]})
    result = await conn.list_files()
    assert result["next_page_token"] is None
    names = {f["name"] for f in result["files"]}
    assert names == {"a.pdf", "b.txt"}
    first = next(f for f in result["files"] if f["name"] == "a.pdf")
    assert first["id"] == "docs::a.pdf"
    assert first["container"] == "docs"
    assert first["modified_time"] == ts.isoformat()


@pytest.mark.asyncio
async def test_list_files_skips_directory_markers(patched_factory):
    patched_factory.return_value = _make_fake_client(
        {"docs": [_blob("folder/"), _blob("folder/real.pdf")]}
    )
    conn = AzureBlobConnector({"container_names": ["docs"]})
    result = await conn.list_files()
    assert [f["key"] for f in result["files"]] == ["folder/real.pdf"]


@pytest.mark.asyncio
async def test_list_files_prefix_filter(patched_factory):
    patched_factory.return_value = _make_fake_client(
        {"docs": [_blob("keep/a.pdf"), _blob("skip/b.pdf")]}
    )
    conn = AzureBlobConnector({"container_names": ["docs"], "prefix": "keep/"})
    result = await conn.list_files()
    assert [f["key"] for f in result["files"]] == ["keep/a.pdf"]


@pytest.mark.asyncio
async def test_list_files_respects_max_files(patched_factory):
    patched_factory.return_value = _make_fake_client(
        {"docs": [_blob(f"f{i}.pdf") for i in range(10)]}
    )
    conn = AzureBlobConnector({"container_names": ["docs"]})
    result = await conn.list_files(max_files=3)
    assert len(result["files"]) == 3


@pytest.mark.asyncio
async def test_list_files_auto_discovers_containers(patched_factory):
    patched_factory.return_value = _make_fake_client(
        {"c1": [_blob("a.pdf")], "c2": [_blob("b.pdf")]}
    )
    conn = AzureBlobConnector({})  # no container_names → auto-discover
    result = await conn.list_files()
    assert {f["container"] for f in result["files"]} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# get_file_content
# ---------------------------------------------------------------------------


def _patch_download(client, content=b"hello", content_type="", last_modified=None, size=None):
    downloader = MagicMock()
    downloader.readall.return_value = content
    props = MagicMock()
    props.content_settings.content_type = content_type
    props.last_modified = last_modified
    props.size = size if size is not None else len(content)
    downloader.properties = props
    blob_client = MagicMock()
    blob_client.download_blob.return_value = downloader
    client.get_blob_client.return_value = blob_client


@pytest.mark.asyncio
async def test_get_file_content_maps_document(patched_factory):
    ts = datetime(2026, 2, 2, tzinfo=UTC)
    client = _make_fake_client({"docs": []})
    _patch_download(client, content=b"pdfbytes", content_type="application/pdf", last_modified=ts)
    patched_factory.return_value = client

    conn = AzureBlobConnector({"container_names": ["docs"]})
    doc = await conn.get_file_content("docs::report.pdf")

    assert doc.id == "docs::report.pdf"
    assert doc.filename == "report.pdf"
    assert doc.content == b"pdfbytes"
    assert doc.mimetype == "application/pdf"
    assert doc.source_url == "azure://docs/report.pdf"
    assert doc.modified_time == ts
    assert doc.metadata["azure_container"] == "docs"
    assert doc.metadata["azure_blob"] == "report.pdf"


@pytest.mark.asyncio
async def test_get_file_content_owner_based_acl_has_no_principals(patched_factory):
    client = _make_fake_client({"docs": []})
    _patch_download(client, content=b"x", content_type="text/plain")
    patched_factory.return_value = client

    conn = AzureBlobConnector({"container_names": ["docs"]})
    doc = await conn.get_file_content("docs::a.txt")
    assert doc.acl.allowed_principals == []
    assert doc.acl.allowed_users == []
    assert doc.acl.allowed_groups == []
    assert doc.acl.owner is None


@pytest.mark.asyncio
async def test_get_file_content_mime_fallback_to_extension(patched_factory):
    client = _make_fake_client({"docs": []})
    # Generic octet-stream should be ignored in favor of the .pdf extension guess.
    _patch_download(client, content=b"x", content_type="application/octet-stream")
    patched_factory.return_value = client

    conn = AzureBlobConnector({"container_names": ["docs"]})
    doc = await conn.get_file_content("docs::file.pdf")
    assert doc.mimetype == "application/pdf"


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success(patched_factory):
    patched_factory.return_value = _make_fake_client({"docs": []})
    conn = AzureBlobConnector({})
    assert await conn.authenticate() is True
    assert conn.is_authenticated is True


@pytest.mark.asyncio
async def test_authenticate_failure(patched_factory):
    client = MagicMock()
    client.list_containers.side_effect = RuntimeError("bad creds")
    patched_factory.return_value = client
    conn = AzureBlobConnector({})
    assert await conn.authenticate() is False
    assert conn.is_authenticated is False


# ---------------------------------------------------------------------------
# build_azure_blob_config (support)
# ---------------------------------------------------------------------------


def test_build_config_connection_string_ok(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(auth_mode="connection_string", connection_string="cs")
    cfg, err = build_azure_blob_config(body, {})
    assert err is None
    assert cfg == {"auth_mode": "connection_string", "connection_string": "cs"}


def test_build_config_connection_string_missing(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(auth_mode="connection_string")
    cfg, err = build_azure_blob_config(body, {})
    assert cfg == {}
    assert "connection_string" in err


def test_build_config_account_key_ok(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(
        auth_mode="account_key", account_name="a", account_key="k", endpoint="http://e"
    )
    cfg, err = build_azure_blob_config(body, {})
    assert err is None
    assert cfg["account_name"] == "a"
    assert cfg["account_key"] == "k"
    assert cfg["endpoint_url"] == "http://e"


def test_build_config_account_key_missing(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(auth_mode="account_key", account_name="a")
    cfg, err = build_azure_blob_config(body, {})
    assert cfg == {}
    assert "account_name and account_key" in err


def test_build_config_env_fallback(monkeypatch):
    _clear_azure_env(monkeypatch)
    monkeypatch.setenv(ACCT_NAME, "envname")
    monkeypatch.setenv(ACCT_KEY, "envkey")
    body = AzureBlobConfigureBody(auth_mode="account_key")
    cfg, err = build_azure_blob_config(body, {})
    assert err is None
    assert cfg["account_name"] == "envname"
    assert cfg["account_key"] == "envkey"


def test_build_config_unknown_mode(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(auth_mode="sas")
    cfg, err = build_azure_blob_config(body, {})
    assert cfg == {}
    assert "Unknown auth_mode" in err


def test_build_config_includes_container_names(monkeypatch):
    _clear_azure_env(monkeypatch)
    body = AzureBlobConfigureBody(
        auth_mode="connection_string", connection_string="cs", container_names=["x", "y"]
    )
    cfg, _ = build_azure_blob_config(body, {})
    assert cfg["container_names"] == ["x", "y"]


# ---------------------------------------------------------------------------
# Webhook / subscription stubs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_stubs_are_noops():
    conn = AzureBlobConnector({})
    assert await conn.setup_subscription() == ""
    assert await conn.handle_webhook({}) == []
    assert conn.extract_webhook_channel_id({}, {}) is None
    assert await conn.cleanup_subscription("sub") is True
