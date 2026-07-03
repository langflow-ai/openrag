"""Unit tests for the Azure Blob Storage connector.

Covers credential resolution (both auth modes + env fallback), client-factory
validation, file listing (prefix filter, dir-marker skip, max_files), composite
file-id round-trip, blob download → ConnectorDocument mapping (owner-based DLS),
authenticate success/failure, IBM_AUTH_ENABLED gating, config-builder validation,
and the webhook stubs.

The sync azure-storage-blob client is replaced with a MagicMock — the connector
offloads it via asyncio.to_thread, so plain mocks work without async machinery.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancements.connectors.azure_blob import api as az_api  # noqa: E402
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
    # "bucket" is the shared bucket-connector contract key (matches aws_s3/ibm_cos)
    # that the file browser reads; carries the Azure container name.
    assert first["bucket"] == "docs"
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
    assert {f["bucket"] for f in result["files"]} == {"c1", "c2"}


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


# ---------------------------------------------------------------------------
# azure_blob_test endpoint (non-persisting credential validation + listing)
# ---------------------------------------------------------------------------


def _test_endpoint_service(existing_connections=None):
    """connector_service mock for azure_blob_test with persistence spies."""
    service = MagicMock()
    cm = service.connection_manager
    cm.list_connections = AsyncMock(return_value=existing_connections or [])
    cm.create_connection = AsyncMock()
    cm.update_connection = AsyncMock()
    cm.get_connection = AsyncMock()
    return service


def _assert_never_persisted(service):
    service.connection_manager.create_connection.assert_not_called()
    service.connection_manager.update_connection.assert_not_called()


@pytest.mark.asyncio
async def test_azure_blob_test_lists_containers_without_persisting(monkeypatch):
    _clear_azure_env(monkeypatch)
    service = _test_endpoint_service()
    user = MagicMock(user_id="u1")
    body = AzureBlobConfigureBody(auth_mode="connection_string", connection_string="cs")

    with patch.object(az_api, "_list_container_names", return_value=["c1", "c2"]) as lister:
        resp = await az_api.azure_blob_test(body, connector_service=service, user=user)

    assert resp.status_code == 200
    assert json.loads(resp.body) == {"containers": ["c1", "c2"]}
    # Containers listed via the resolved config, and nothing was persisted.
    lister.assert_called_once()
    _assert_never_persisted(service)


@pytest.mark.asyncio
async def test_azure_blob_test_does_not_mutate_existing_connection(monkeypatch):
    """Editing an existing connection's credentials via Test must not save them."""
    _clear_azure_env(monkeypatch)
    existing = MagicMock(connection_id="conn-1", config={"connection_string": "old"})
    service = _test_endpoint_service([existing])
    user = MagicMock(user_id="u1")
    body = AzureBlobConfigureBody(
        auth_mode="connection_string", connection_string="new", connection_id="conn-1"
    )

    with patch.object(az_api, "_list_container_names", return_value=["c1"]):
        resp = await az_api.azure_blob_test(body, connector_service=service, user=user)

    assert resp.status_code == 200
    assert json.loads(resp.body)["containers"] == ["c1"]
    _assert_never_persisted(service)


@pytest.mark.asyncio
async def test_azure_blob_test_invalid_config_returns_400_without_persisting(monkeypatch):
    _clear_azure_env(monkeypatch)
    service = _test_endpoint_service()
    user = MagicMock(user_id="u1")
    # connection_string mode with no string → build_azure_blob_config returns an error.
    body = AzureBlobConfigureBody(auth_mode="connection_string")

    with patch.object(az_api, "_list_container_names") as lister:
        resp = await az_api.azure_blob_test(body, connector_service=service, user=user)

    assert resp.status_code == 400
    assert "connection_string" in json.loads(resp.body)["error"]
    lister.assert_not_called()  # never reached the credential test
    _assert_never_persisted(service)


@pytest.mark.asyncio
async def test_azure_blob_test_connection_failure_returns_400_without_persisting(monkeypatch):
    _clear_azure_env(monkeypatch)
    service = _test_endpoint_service()
    user = MagicMock(user_id="u1")
    body = AzureBlobConfigureBody(auth_mode="connection_string", connection_string="cs")

    with patch.object(az_api, "_list_container_names", side_effect=RuntimeError("bad creds")):
        resp = await az_api.azure_blob_test(body, connector_service=service, user=user)

    assert resp.status_code == 400
    assert "Could not connect" in json.loads(resp.body)["error"]
    _assert_never_persisted(service)


# ---------------------------------------------------------------------------
# azure_blob_container_status endpoint (browse list honors ingestion restriction)
# ---------------------------------------------------------------------------


def _status_endpoint_deps(config):
    """connector_service + session_manager mocks for azure_blob_container_status."""
    connection = MagicMock(user_id="u1", connector_type="azure_blob", config=config)
    service = MagicMock()
    service.connection_manager.get_connection = AsyncMock(return_value=connection)
    # OpenSearch client raises so doc-count aggregation is skipped (counts → 0).
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.side_effect = RuntimeError("no opensearch")
    return service, session_manager


@pytest.mark.asyncio
async def test_container_status_restricts_to_allowed_containers():
    """A non-empty container_names allowlist filters out unselected containers."""
    service, session_manager = _status_endpoint_deps({"container_names": ["docs"]})
    user = MagicMock(user_id="u1", jwt_token="t")

    with patch.object(az_api, "_list_container_names", return_value=["docs", "images", "logs"]):
        resp = await az_api.azure_blob_container_status(
            "conn-1",
            connector_service=service,
            session_manager=session_manager,
            user=user,
        )

    names = [c["name"] for c in json.loads(resp.body)["containers"]]
    assert names == ["docs"]


@pytest.mark.asyncio
async def test_container_status_no_restriction_shows_all_containers():
    """An empty/absent allowlist leaves every accessible container browsable."""
    service, session_manager = _status_endpoint_deps({"container_names": []})
    user = MagicMock(user_id="u1", jwt_token="t")

    with patch.object(az_api, "_list_container_names", return_value=["docs", "images"]):
        resp = await az_api.azure_blob_container_status(
            "conn-1",
            connector_service=service,
            session_manager=session_manager,
            user=user,
        )

    names = [c["name"] for c in json.loads(resp.body)["containers"]]
    assert names == ["docs", "images"]


def _status_deps_with_counts(config, agg_buckets):
    """Deps for azure_blob_container_status with a *working* OpenSearch aggregation.

    Unlike `_status_endpoint_deps` (which raises so counts collapse to 0), this
    returns an AsyncOpenSearch-shaped client whose ``search`` is awaitable and
    yields ``agg_buckets``. Regression guard for the missing-``await`` bug: the
    handler must ``await opensearch_client.search(...)`` — if it doesn't, the
    coroutine's ``.get(...)`` raises, the bare ``except`` swallows it, and every
    count silently reads 0 (which these assertions would then catch).
    """
    connection = MagicMock(user_id="u1", connector_type="azure_blob", config=config)
    service = MagicMock()
    service.connection_manager.get_connection = AsyncMock(return_value=connection)
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={"aggregations": {"doc_ids": {"buckets": agg_buckets}}}
    )
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    return service, session_manager


@pytest.mark.asyncio
async def test_container_status_reports_ingested_counts():
    """Per-container ingested_count / is_synced reflect the OpenSearch aggregation.

    Guards against the missing-``await`` regression where every container falsely
    reported ``ingested_count: 0, is_synced: false``.
    """
    buckets = [
        {"key": "docs::a.pdf"},
        {"key": "docs::b.pdf"},
        {"key": "images::c.png"},
    ]
    service, session_manager = _status_deps_with_counts({"container_names": []}, buckets)
    user = MagicMock(user_id="u1", jwt_token="t")

    with patch.object(az_api, "_list_container_names", return_value=["docs", "images", "logs"]):
        resp = await az_api.azure_blob_container_status(
            "conn-1",
            connector_service=service,
            session_manager=session_manager,
            user=user,
        )

    by_name = {c["name"]: c for c in json.loads(resp.body)["containers"]}
    assert by_name["docs"]["ingested_count"] == 2
    assert by_name["docs"]["is_synced"] is True
    assert by_name["images"]["ingested_count"] == 1
    assert by_name["images"]["is_synced"] is True
    # No indexed docs → not synced.
    assert by_name["logs"]["ingested_count"] == 0
    assert by_name["logs"]["is_synced"] is False


@pytest.mark.asyncio
async def test_container_status_counts_zero_when_opensearch_unavailable():
    """A failed aggregation degrades gracefully to zero counts (not a 500)."""
    service, session_manager = _status_endpoint_deps({"container_names": []})
    user = MagicMock(user_id="u1", jwt_token="t")

    with patch.object(az_api, "_list_container_names", return_value=["docs"]):
        resp = await az_api.azure_blob_container_status(
            "conn-1",
            connector_service=service,
            session_manager=session_manager,
            user=user,
        )

    entry = json.loads(resp.body)["containers"][0]
    assert entry == {"name": "docs", "ingested_count": 0, "is_synced": False}


# ---------------------------------------------------------------------------
# azure_blob_list_containers endpoint (also honors the ingestion restriction)
# ---------------------------------------------------------------------------


def _list_endpoint_service(config):
    """connector_service mock for azure_blob_list_containers."""
    connection = MagicMock(user_id="u1", connector_type="azure_blob", config=config)
    service = MagicMock()
    service.connection_manager.get_connection = AsyncMock(return_value=connection)
    return service


@pytest.mark.asyncio
async def test_list_containers_restricts_to_allowed_containers():
    """A non-empty container_names allowlist filters out unselected containers."""
    service = _list_endpoint_service({"container_names": ["docs"]})
    user = MagicMock(user_id="u1")

    with patch.object(az_api, "_list_container_names", return_value=["docs", "images", "logs"]):
        resp = await az_api.azure_blob_list_containers(
            "conn-1", connector_service=service, user=user
        )

    assert json.loads(resp.body)["containers"] == ["docs"]


@pytest.mark.asyncio
async def test_list_containers_no_restriction_shows_all_containers():
    """An empty/absent allowlist leaves every accessible container listed."""
    service = _list_endpoint_service({"container_names": []})
    user = MagicMock(user_id="u1")

    with patch.object(az_api, "_list_container_names", return_value=["docs", "images"]):
        resp = await az_api.azure_blob_list_containers(
            "conn-1", connector_service=service, user=user
        )

    assert json.loads(resp.body)["containers"] == ["docs", "images"]
