"""Operator-enabled wheel discovery and the generic customer-connector HTTP contract."""

import importlib
import json
import shutil
import subprocess
import sys
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from api import plugin_connectors
from connectors import registry
from connectors.connection_manager import ConnectionConfig, ConnectionManager
from dependencies import get_connector_service, get_db_session, get_session_manager
from session_manager import User
from utils import encryption

pytestmark = pytest.mark.openrag_skip_app_onboard


@pytest.fixture
def installed_wheel(tmp_path, monkeypatch):
    """Build and pip-install a real entry-point wheel outside the source tree."""
    wheel = tmp_path / "openrag_demo_plugin-1.0-py3-none-any.whl"
    module = """from connectors.base import BaseConnector
class DemoConnector(BaseConnector):
    CONNECTOR_API_VERSION = 1
    CONNECTOR_TYPE = "installed_demo"
    CONNECTOR_KIND = "bucket"
    CONNECTOR_NAME = "Installed Demo"
    CONNECTOR_DESCRIPTION = "Wheel-installed demo"
    CONNECTOR_ICON = "database"
    BROWSE_CAPABILITY = "hierarchical"
    CONFIG_FIELDS = (dict(name="endpoint", label="Endpoint", type="text", required=True),
                     dict(name="domain", label="Domain", type="text", required=False),
                     dict(name="username", label="Username", type="secret", required=True),
                     dict(name="password", label="Password", type="secret", required=True))
    SECRET_CONFIG_KEYS = ("username", "password")
    CREDENTIAL_PAIR = ("username", "password")
    async def authenticate(self):
        self._authenticated = bool(self.config.get("password") == "valid")
        return self._authenticated
    async def list_children(self, parent_id=None, cursor=None, page_size=100):
        if parent_id not in (None, "root") or cursor not in (None, "next"):
            raise ValueError("out of scope")
        return {"nodes": [{"id": "file-1", "parent_id": parent_id, "kind": "file",
                           "name": "Report.pdf", "size": 7}], "next_cursor": None}
    async def list_files(self, *args, **kwargs):
        return {"files": [], "next_page_token": None}
    async def get_file_content(self, file_id):
        raise ValueError(file_id)
    async def setup_subscription(self, *args, **kwargs):
        return None
    async def cleanup_subscription(self, *args, **kwargs):
        return None
    async def handle_webhook(self, *args, **kwargs):
        return []
"""
    dist_info = "openrag_demo_plugin-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("openrag_demo_plugin.py", module)
        archive.writestr(
            dist_info + "METADATA",
            "Metadata-Version: 2.1\nName: openrag-demo-plugin\nVersion: 1.0\n",
        )
        archive.writestr(
            dist_info + "WHEEL",
            "Wheel-Version: 1.0\nGenerator: plugin-host-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            dist_info + "entry_points.txt",
            "[openrag.connectors.v1]\ninstalled_demo = openrag_demo_plugin:DemoConnector\n",
        )
        archive.writestr(
            dist_info + "RECORD",
            "\n".join(
                f"{path},,"
                for path in (
                    "openrag_demo_plugin.py",
                    dist_info + "METADATA",
                    dist_info + "WHEEL",
                    dist_info + "entry_points.txt",
                    dist_info + "RECORD",
                )
            )
            + "\n",
        )
    destination = tmp_path / "site-packages"
    installer = (
        [shutil.which("uv"), "pip", "install", "--no-deps", "--offline"]
        if shutil.which("uv")
        else [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index"]
    )
    subprocess.run(
        [*installer, "--target", str(destination), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.syspath_prepend(str(destination))
    importlib.invalidate_caches()
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    yield
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    sys.modules.pop("openrag_demo_plugin", None)


@pytest.mark.asyncio
async def test_disabled_plugin_preserves_secret_envelopes_across_unrelated_save(
    installed_wheel, monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    connection_file = tmp_path / "connections.json"
    writer = ConnectionManager(str(connection_file))
    writer.connections["plugin-1"] = ConnectionConfig(
        connection_id="plugin-1",
        connector_type="installed_demo",
        name="Plugin",
        user_id="alice",
        config={
            "endpoint": "https://intranet.example",
            "username": "domain\\alice",
            "password": "valid",
        },
    )
    await writer.save_connections()
    original = json.loads(connection_file.read_text())["connections"][0]["config"]
    assert original["username"]["algorithm"] == "AES-256-GCM"
    assert original["password"]["algorithm"] == "AES-256-GCM"

    monkeypatch.delenv("OPENRAG_CONNECTOR_PLUGINS")
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    rollback = ConnectionManager(str(connection_file))
    await rollback.load_connections()
    assert rollback.connections["plugin-1"].config["username"] == original["username"]
    assert rollback.connections["plugin-1"].config["password"] == original["password"]
    rollback.connections["plugin-1"].name = "Unrelated update"
    await rollback.save_connections()
    saved = json.loads(connection_file.read_text())["connections"][0]
    assert saved["config"]["username"] == original["username"]
    assert saved["config"]["password"] == original["password"]
    assert "domain\\\\alice" not in connection_file.read_text()
    assert "valid" not in connection_file.read_text()

    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    restored = ConnectionManager(str(connection_file))
    await restored.load_connections()
    assert restored.connections["plugin-1"].config["username"] == "domain\\alice"
    assert restored.connections["plugin-1"].config["password"] == "valid"


def test_installed_wheel_is_invisible_until_enabled_and_freezes(installed_wheel, monkeypatch):
    monkeypatch.delenv("OPENRAG_CONNECTOR_PLUGINS", raising=False)
    assert registry.get_plugin_connector_class("installed_demo") is None
    assert "openrag_demo_plugin" not in sys.modules
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    assert registry.get_plugin_connector_class("installed_demo") is None  # frozen until restart
    monkeypatch.setattr(registry, "_plugin_connectors", None)  # simulate fresh process
    assert registry.get_plugin_connector_class("installed_demo").CONNECTOR_NAME == "Installed Demo"
    assert registry.get_plugin_secret_keys() == {"username", "password"}


def test_enabled_collision_and_missing_wheel_fail_at_startup(installed_wheel, monkeypatch):
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo,does_not_exist")
    with pytest.raises(RuntimeError, match="does_not_exist.*not installed"):
        registry.get_route_connector_classes()
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "sharepoint")
    with pytest.raises(RuntimeError, match="not installed|collides"):
        registry.get_route_connector_classes()
    monkeypatch.setattr(registry, "_plugin_connectors", None)
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    monkeypatch.setattr(
        registry,
        "BUILTIN_CONNECTORS",
        [*registry.BUILTIN_CONNECTORS, type("Collision", (), {"CONNECTOR_TYPE": "installed_demo"})],
    )
    with pytest.raises(RuntimeError, match="collides"):
        registry.get_route_connector_classes()


def test_incompatible_entry_point_version_fails_at_startup(installed_wheel, monkeypatch):
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    cls = importlib.import_module("openrag_demo_plugin").DemoConnector
    monkeypatch.setattr(cls, "CONNECTOR_API_VERSION", 2)
    with pytest.raises(RuntimeError, match="CONNECTOR_API_VERSION=1"):
        registry.get_route_connector_classes()


async def _no_db_session():
    # Connector-access policy is not enforced in unit tests unless a test
    # patches it, so the routes never query the session.
    yield None


def _plugin_app(manager, session_manager, user):
    """The four generic plugin routes, wired to test doubles."""
    app = FastAPI()
    app.add_api_route(
        "/connectors/{connector_type}/plugin-defaults",
        plugin_connectors.plugin_defaults,
        methods=["GET"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/plugin-test", plugin_connectors.plugin_test, methods=["POST"]
    )
    app.add_api_route(
        "/connectors/{connector_type}/plugin-configure",
        plugin_connectors.plugin_configure,
        methods=["POST"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/{connection_id}/picker/children",
        plugin_connectors.plugin_picker_children,
        methods=["GET"],
    )
    app.dependency_overrides[get_connector_service] = lambda: SimpleNamespace(
        connection_manager=manager
    )
    app.dependency_overrides[get_session_manager] = lambda: session_manager
    app.dependency_overrides[get_db_session] = _no_db_session
    for route in app.routes:
        if hasattr(route, "dependant"):
            for dependency in route.dependant.dependencies:
                if dependency.name == "user":
                    app.dependency_overrides[dependency.call] = lambda: user
    return app


@pytest.mark.asyncio
async def test_plugin_form_auth_persistence_and_owner_scoped_picker(
    installed_wheel, monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    manager = ConnectionManager(str(tmp_path / "connections.json"))

    index_state = {"available": True}

    class IndexedFiles:
        async def search(self, *, index, body):
            if not index_state["available"]:
                raise RuntimeError("Index unavailable")
            filters = body["query"]["bool"]["filter"]
            assert {"terms": {"connector_file_id": ["file-1"]}} in filters[1]["bool"]["should"]
            return {
                "aggregations": {
                    "by_connector_file_id": {"buckets": []},
                    "by_document_id": {"buckets": []},
                }
            }

    user = User(user_id="alice", name="Alice", email="alice@example.com")
    app = _plugin_app(
        manager,
        SimpleNamespace(get_user_opensearch_client=lambda user_id, token: IndexedFiles()),
        user,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        base = "/connectors/installed_demo"
        initial = await client.get(base + "/plugin-defaults")
        assert initial.status_code == 200
        assert initial.json()["config_fields"][2]["type"] == "secret"
        assert initial.json()["config"] == {}
        config = {
            "endpoint": "https://intranet.example",
            "domain": "EXAMPLE",
            "username": "domain\\alice",
            "password": "valid",
        }
        bad = await client.post(
            base + "/plugin-test", json={"config": {**config, "user_id": "bob"}}
        )
        assert bad.status_code == 422 and "valid" not in bad.text
        preview = await client.post(base + "/plugin-test", json={"config": config})
        assert preview.json() == {"status": "ok"} and not manager.connections
        monkeypatch.delenv("OPENRAG_ENCRYPTION_KEY")
        no_key = await client.post(base + "/plugin-configure", json={"config": config})
        assert no_key.status_code == 503
        assert not manager.connections_file.exists()
        monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
        created = await client.post(base + "/plugin-configure", json={"config": config})
        assert created.status_code == 200
        conn_id = created.json()["connection_id"]
        raw = json.loads((tmp_path / "connections.json").read_text())
        assert raw["connections"][0]["config"]["username"]["algorithm"] == "AES-256-GCM"
        assert raw["connections"][0]["config"]["password"]["algorithm"] == "AES-256-GCM"
        assert "valid" not in (tmp_path / "connections.json").read_text()
        assert (tmp_path / "connections.json").stat().st_mode & 0o777 == 0o600
        persisted = ConnectionManager(str(tmp_path / "connections.json"))
        await persisted.load_connections()
        assert (await persisted.get_connection(conn_id)).config["password"] == "valid"
        defaults = await client.get(base + "/plugin-defaults")
        assert defaults.json()["secrets_set"] == {"username": True, "password": True}
        assert "username" not in defaults.json()["config"] and "valid" not in defaults.text
        broken_pair = await client.post(
            base + "/plugin-configure",
            json={"connection_id": conn_id, "config": {"username": "other-user"}},
        )
        assert broken_pair.status_code == 422
        unchanged_pair = await client.post(
            base + "/plugin-test",
            json={"connection_id": conn_id, "config": {"endpoint": "https://intranet.example"}},
        )
        assert unchanged_pair.json() == {"status": "ok"}
        rotated = await client.post(
            base + "/plugin-configure",
            json={
                "connection_id": conn_id,
                "config": {"username": "other-user", "password": "valid"},
            },
        )
        assert rotated.json() == {"connection_id": conn_id, "status": "connected"}
        assert (await manager.get_connection(conn_id)).config["username"] == "other-user"
        assert (
            json.loads(manager.connections_file.read_text())["connections"][0]["config"][
                "username"
            ]["algorithm"]
            == "AES-256-GCM"
        )
        cleared = await client.post(
            base + "/plugin-configure",
            json={"connection_id": conn_id, "config": {"domain": ""}},
        )
        assert cleared.status_code == 200
        assert (await manager.get_connection(conn_id)).config["domain"] == ""
        page = await client.get(
            base + f"/{conn_id}/picker/children", params={"parent_id": "root", "page_size": 1}
        )
        assert page.json() == {
            "nodes": [
                {
                    "id": "file-1",
                    "parent_id": "root",
                    "kind": "file",
                    "name": "Report.pdf",
                    "size": 7,
                    "is_ingested": False,
                    "is_stale": False,
                }
            ],
            "next_cursor": None,
        }
        index_state["available"] = False
        assert (await client.get(base + f"/{conn_id}/picker/children")).status_code == 503
        index_state["available"] = True
        assert (
            await client.get(base + f"/{conn_id}/picker/children", params={"page_size": 201})
        ).status_code == 422
        assert (
            await client.get(base + f"/{conn_id}/picker/children", params={"parent_id": "outside"})
        ).status_code == 400
        assert (
            await client.get("/connectors/sharepoint/" + conn_id + "/picker/children")
        ).status_code == 404
        user.user_id = "bob"
        assert (await client.get(base + f"/{conn_id}/picker/children")).status_code == 404
        assert (
            await client.get(base + "/plugin-defaults", params={"connection_id": conn_id})
        ).status_code == 404
        assert (
            await client.post(
                base + "/plugin-configure", json={"connection_id": conn_id, "config": config}
            )
        ).status_code == 404
        monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
        assert (await client.get(base + "/plugin-defaults")).status_code == 404
        assert "installed_demo" not in manager.get_available_connector_types("alice")


@pytest.mark.asyncio
async def test_flat_plugin_pages_files_and_rejects_folders(installed_wheel, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    cls = registry.get_plugin_connector_class("installed_demo")
    monkeypatch.setattr(cls, "BROWSE_CAPABILITY", "flat")

    async def list_files(self, page_token=None, max_files=None):
        assert max_files == 1
        if page_token is None:
            return {
                "files": [{"id": "first", "name": "First.pdf", "size": 10}],
                "next_page_token": "page-two",
            }
        if page_token == "page-two":
            return {
                "files": [{"id": "second", "name": "Second.pdf", "size": 20}],
                "next_page_token": None,
            }
        raise ValueError("Invalid cursor")

    monkeypatch.setattr(cls, "list_files", list_files)
    manager = ConnectionManager(str(tmp_path / "connections.json"))
    manager.connections["flat-owned"] = ConnectionConfig(
        connection_id="flat-owned",
        connector_type="installed_demo",
        name="Flat",
        config={"endpoint": "https://example.com", "username": "alice", "password": "valid"},
        user_id="alice",
    )
    indexed_queries = []

    class IndexedFiles:
        async def search(self, *, index, body):
            indexed_queries.append(body)
            return {
                "aggregations": {
                    "by_connector_file_id": {"buckets": []},
                    "by_document_id": {"buckets": []},
                }
            }

    user = User(user_id="alice", name="Alice", email="alice@example.com")
    app = _plugin_app(
        manager,
        SimpleNamespace(get_user_opensearch_client=lambda user_id, token: IndexedFiles()),
        user,
    )
    url = "/connectors/installed_demo/flat-owned/picker/children"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get(url, params={"page_size": 1})
        assert first.status_code == 200
        assert first.json() == {
            "nodes": [
                {
                    "id": "first",
                    "parent_id": None,
                    "kind": "file",
                    "name": "First.pdf",
                    "size": 10,
                    "is_ingested": False,
                    "is_stale": False,
                }
            ],
            "next_cursor": "page-two",
        }
        second = await client.get(url, params={"page_size": 1, "cursor": "page-two"})
        assert second.status_code == 200
        assert second.json()["nodes"][0]["id"] == "second"
        assert second.json()["next_cursor"] is None
        assert len(indexed_queries) == 2
        assert (await client.get(url, params={"parent_id": "folder"})).status_code == 400
        assert (
            await client.get(url, params={"cursor": "unknown", "page_size": 1})
        ).status_code == 400


@pytest.mark.asyncio
async def test_blocked_plugin_routes_return_403_before_touching_credentials_or_source(
    installed_wheel, monkeypatch, tmp_path
):
    """Workspace connector-access policy (review 1d): when an admin blocks the
    plugin, none of its routes may store credentials, probe the source, or
    browse it — the UI hiding the card is not the enforcement point."""
    from api import connectors as connectors_api

    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    # CONNECTOR_TYPES is frozen at import, before this test enables the plugin.
    monkeypatch.setattr(
        connectors_api, "CONNECTOR_TYPES", (*connectors_api.CONNECTOR_TYPES, "installed_demo")
    )
    monkeypatch.setattr(connectors_api, "is_connector_access_policy_enforced", lambda: True)
    allowed = AsyncMock(return_value=False)
    monkeypatch.setattr(connectors_api, "is_connector_allowed_for_request", allowed)

    cls = registry.get_plugin_connector_class("installed_demo")
    authenticate = AsyncMock(return_value=True)
    list_children = AsyncMock(return_value={"nodes": [], "next_cursor": None})
    monkeypatch.setattr(cls, "authenticate", authenticate)
    monkeypatch.setattr(cls, "list_children", list_children)

    manager = ConnectionManager(str(tmp_path / "connections.json"))
    seeded_config = {"endpoint": "https://intranet.example", "username": "a", "password": "p"}
    manager.connections["owned"] = ConnectionConfig(
        connection_id="owned",
        connector_type="installed_demo",
        name="Demo",
        config=dict(seeded_config),
        user_id="alice",
    )
    user = User(user_id="alice", name="Alice", email="alice@example.com")
    app = _plugin_app(manager, SimpleNamespace(), user)
    config = {"endpoint": "https://intranet.example", "username": "alice", "password": "valid"}
    base = "/connectors/installed_demo"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [
            await client.get(base + "/plugin-defaults"),
            await client.post(base + "/plugin-test", json={"config": config}),
            await client.post(base + "/plugin-configure", json={"config": config}),
            await client.post(
                base + "/plugin-configure", json={"connection_id": "owned", "config": config}
            ),
            await client.get(base + "/owned/picker/children"),
        ]
        assert [response.status_code for response in responses] == [403] * len(responses)
        assert all("valid" not in response.text for response in responses)
        authenticate.assert_not_awaited()
        list_children.assert_not_awaited()
        assert list(manager.connections) == ["owned"]
        assert manager.connections["owned"].config == seeded_config
        assert not manager.connections_file.exists()

        # The gate opens once the workspace allows the connector again.
        allowed.return_value = True
        assert (await client.get(base + "/plugin-defaults")).status_code == 200


def _plugin_record(password_value):
    return {
        "connection_id": "plugin-1",
        "connector_type": "installed_demo",
        "name": "Plugin",
        "config": {
            "endpoint": "https://intranet.example",
            "username": "domain\\alice",
            "password": password_value,
        },
        "user_id": "alice",
    }


@pytest.mark.asyncio
async def test_undecryptable_plugin_record_does_not_drop_other_connections(
    installed_wheel, monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    connection_file = tmp_path / "connections.json"
    writer = ConnectionManager(str(connection_file))
    writer.connections["plugin-1"] = ConnectionConfig(**_plugin_record("valid"))
    writer.connections["drive-1"] = ConnectionConfig(
        connection_id="drive-1",
        connector_type="google_drive",
        name="Drive",
        config={"client_secret": "drive-secret"},
        user_id="bob",
    )
    await writer.save_connections()
    original_plugin = next(
        c
        for c in json.loads(connection_file.read_text())["connections"]
        if c["connection_id"] == "plugin-1"
    )

    # Rotated key: the plugin record can no longer be decrypted.
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "a-different-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    rotated = ConnectionManager(str(connection_file))
    await rotated.load_connections()
    assert "plugin-1" not in rotated.connections
    assert "drive-1" in rotated.connections

    rotated.connections["drive-1"].name = "Unrelated update"
    await rotated.save_connections()
    saved = {c["connection_id"]: c for c in json.loads(connection_file.read_text())["connections"]}
    assert saved["plugin-1"] == original_plugin
    assert saved["drive-1"]["name"] == "Unrelated update"

    # Restoring the key brings the quarantined record back.
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    restored = ConnectionManager(str(connection_file))
    await restored.load_connections()
    assert restored.connections["plugin-1"].config["password"] == "valid"
    assert restored._unloadable_records == []


@pytest.mark.asyncio
async def test_plaintext_plugin_secret_is_quarantined(installed_wheel, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "isolated-test-master-secret")
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "installed_demo")
    connection_file = tmp_path / "connections.json"
    record = _plugin_record("plaintext-password")
    connection_file.write_text(json.dumps({"connections": [record]}))

    manager = ConnectionManager(str(connection_file))
    await manager.load_connections()
    assert "plugin-1" not in manager.connections

    await manager.save_connections()
    assert json.loads(connection_file.read_text())["connections"] == [record]
