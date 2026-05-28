import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import jwt
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_canonical_group_role_is_compact_and_provider_scoped():
    from utils.group_acl import canonical_group_role

    role = canonical_group_role(
        "m365",
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )

    assert role == "g:m365:AAAAAAAAAAAAAAAAAAAAAQ:AAAAAAAAAAAAAAAAAAAAAg"


def test_canonical_user_principal_is_compact_and_provider_scoped():
    from utils.group_acl import canonical_user_principal

    principal = canonical_user_principal(
        "gdrive",
        "example.com",
        "Owner@Example.com",
    )

    assert principal.startswith("u:gdrive:")
    assert principal == canonical_user_principal(
        "gdrive",
        "EXAMPLE.COM",
        "owner@example.com",
    )


def test_opensearch_jwt_does_not_include_connector_group_roles(monkeypatch):
    from session_manager import SessionManager, User

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")

    manager = SessionManager("test")
    user = User(user_id="user-1", email="user@example.com", name="User")

    token = manager.create_opensearch_jwt_token(user, ttl_seconds=60)
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["roles"] == ["openrag_user"]
    assert payload["sub"] == "user-1"


def test_opensearch_jwt_default_ttl_tracks_ingestion_timeout(monkeypatch):
    from session_manager import SessionManager, User

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")
    monkeypatch.delenv("OPENRAG_OPENSEARCH_JWT_TTL", raising=False)
    monkeypatch.setattr("config.settings.INGESTION_TIMEOUT", 3600)

    manager = SessionManager("test")
    user = User(user_id="user-1", email="user@example.com", name="User")

    token = manager.create_opensearch_jwt_token(user)
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["exp"] - payload["iat"] == 3900


@pytest.mark.asyncio
async def test_group_acl_service_uses_connector_hooks_generically():
    from services.group_acl_service import GroupACLService
    from session_manager import User

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            assert user_id == "user-1"
            return [
                Connection("sharepoint-1", "sharepoint"),
                Connection("custom-1", "custom"),
            ]

    class Connector:
        def __init__(self, roles):
            self.roles = roles

        async def get_current_user_group_roles(self):
            return self.roles

    class ConnectorService:
        connection_manager = ConnectionManager()

        async def get_connector(self, connection_id):
            return {
                "sharepoint-1": Connector(["g:m365:t:g1", "g:m365:t:g2"]),
                "custom-1": Connector(["g:custom:t:g2", "g:m365:t:g1"]),
            }[connection_id]

    service = GroupACLService(ConnectorService(), cache_ttl_seconds=0)
    roles = await service.get_user_group_roles(
        User(user_id="user-1", email="user@example.com", name="User")
    )

    assert roles == ["g:m365:t:g1", "g:m365:t:g2", "g:custom:t:g2"]
    assert service._cache == {}
    assert service._locks == {}


@pytest.mark.asyncio
async def test_group_acl_service_disabled_cache_does_not_retain_locks():
    from services.group_acl_service import GroupACLService
    from session_manager import User

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            return [Connection(f"{user_id}-connection", "custom")]

    class Connector:
        async def get_current_user_group_roles(self):
            return ["g:custom:t:g1"]

    class ConnectorService:
        connection_manager = ConnectionManager()

        async def get_connector(self, connection_id):
            return Connector()

    service = GroupACLService(ConnectorService(), cache_ttl_seconds=0)

    for user_id in ("user-1", "user-2"):
        roles = await service.get_user_group_roles(User(user_id=user_id, email=None, name=None))
        assert roles == ["g:custom:t:g1"]

    assert service._cache == {}
    assert service._locks == {}


def test_group_acl_service_invalidation_drops_cache_and_locks():
    from services.group_acl_service import GroupACLService

    service = GroupACLService(connector_service=object(), cache_ttl_seconds=60)
    service._cache["user-1"] = (999999.0, ["g:test:t:g1"])
    service._locks["user-1"] = asyncio.Lock()
    service._cache["user-2"] = (999999.0, ["g:test:t:g2"])
    service._locks["user-2"] = asyncio.Lock()

    service.invalidate_user("user-1")

    assert "user-1" not in service._cache
    assert "user-1" not in service._locks
    assert "user-2" in service._cache
    assert "user-2" in service._locks

    service.clear()

    assert service._cache == {}
    assert service._locks == {}


def test_security_roles_include_acl_dls_queries():
    for rel_path in ("securityconfig/roles.yml", "cloud_securityconfig/roles.yml"):
        roles = yaml.safe_load((ROOT / rel_path).read_text())
        index_permissions = roles["openrag_user_role"]["index_permissions"]
        cluster_permissions = roles["openrag_user_role"]["cluster_permissions"]
        assert "indices:data/write/bulk" not in cluster_permissions
        assert "indices:data/write/index" not in cluster_permissions
        assert not any("alerting" in permission for permission in cluster_permissions)

        document_permission = index_permissions[0]
        document_actions = document_permission["allowed_actions"]
        assert "read" in document_actions
        assert "crud" not in document_actions
        assert "indices:data/write/index" not in document_actions
        assert "indices:data/write/update/byquery" not in document_actions
        assert "indices:admin/mappings/put" not in document_actions

        dls = index_permissions[0]["dls"]
        assert '{"term":{"owner":"${user.name}"}}' in dls
        assert '{"term":{"owner":"${attr.jwt.email}"}}' in dls
        assert '{"term":{"allowed_users":"${user.name}"}}' in dls
        assert '{"term":{"allowed_users":"${attr.jwt.email}"}}' in dls
        assert '{"terms":{"allowed_groups":[${user.roles}]}}' not in dls
        assert (
            '{"terms":{"allowed_principals":{"index":"openrag_dls_principals",'
            '"id":"${user.name}","path":"principals"}}}' in dls
        )
        principal_permission = next(
            permission
            for permission in index_permissions
            if "openrag_dls_principals" in permission["index_patterns"]
        )
        assert "crud" not in principal_permission["allowed_actions"]
        assert "indices:data/write/index" not in principal_permission["allowed_actions"]
        assert principal_permission["dls"] == '{"term":{"user_name":"${user.name}"}}\n'


@pytest.mark.asyncio
async def test_dls_principal_service_writes_user_lookup_rows():
    from services.dls_principal_service import DLSPrincipalService
    from session_manager import User

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            assert user_id == "user-1"
            return [
                Connection("drive-1", "google_drive"),
                Connection("inactive-1", "google_drive", is_active=False),
            ]

        def get_auth_user_principals(self, user):
            assert user.email == "user@example.com"
            return ["u:gdrive:example.com:user"]

    class Connector:
        async def get_current_user_principals(self):
            return ["u:gdrive:t:user", "u:gdrive:t:user"]

        async def get_current_user_group_roles(self):
            return ["g:gdrive:t:engineering"]

        async def get_current_user_principal_labels(self):
            return [
                {
                    "principal": "g:gdrive:t:engineering",
                    "kind": "group",
                    "provider": "gdrive",
                    "display_name": "Engineering",
                }
            ]

    class ConnectorService:
        connection_manager = ConnectionManager()

        async def get_connector(self, connection_id):
            assert connection_id == "drive-1"
            return Connector()

    class Indices:
        async def exists(self, index):
            assert index == "openrag_dls_principals"
            return False

        async def create(self, index, body):
            assert index == "openrag_dls_principals"
            assert body["mappings"]["properties"]["principals"]["type"] == "keyword"

    class OpenSearchClient:
        indices = Indices()

        def __init__(self):
            self.index_calls = []

        async def index(self, **kwargs):
            self.index_calls.append(kwargs)

    opensearch_client = OpenSearchClient()
    service = DLSPrincipalService(ConnectorService(), opensearch_client=opensearch_client)

    principals = await service.refresh_user_principals(
        User(
            user_id="user-1",
            email="user@example.com",
            name="User",
            provider="google",
            opensearch_username="ibmlhapikey_user-1",
        ),
        group_roles=["g:gdrive:t:engineering"],
    )

    assert principals[0] == "g:gdrive:t:engineering"
    assert "u:gdrive:t:user" in principals
    assert "u:gdrive:example.com:user" in principals
    assert len(opensearch_client.index_calls) == 2
    assert {call["id"] for call in opensearch_client.index_calls} == {
        "ibmlhapikey_user-1",
        "user-1",
    }
    body = opensearch_client.index_calls[0]["body"]
    assert any(
        label.get("principal") == "g:gdrive:t:engineering"
        and label.get("kind") == "group"
        and label.get("provider") == "gdrive"
        and label.get("display_name") == "Engineering"
        for label in body["principal_labels"]
    )
    assert any(
        label.get("principal") == "u:gdrive:example.com:user"
        and label.get("kind") == "user"
        and label.get("provider") == "gdrive"
        and label.get("display_name") == "User"
        and label.get("email") == "user@example.com"
        and label.get("external_id") == "user-1"
        for label in body["principal_labels"]
    )
    for call in opensearch_client.index_calls:
        assert call["index"] == "openrag_dls_principals"
        assert call["refresh"] == "wait_for"
        assert call["body"]["principals"] == principals


@pytest.mark.asyncio
async def test_dls_principal_service_caches_and_coalesces_lookup_refreshes():
    from services.dls_principal_service import DLSPrincipalService
    from session_manager import User

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class ConnectionManager:
        def __init__(self):
            self.list_calls = 0

        async def list_connections(self, user_id=None):
            assert user_id == "user-1"
            self.list_calls += 1
            await asyncio.sleep(0.01)
            return [Connection("drive-1", "google_drive")]

        def get_auth_user_principals(self, user):
            assert user.email == "user@example.com"
            return ["u:gdrive:example.com:user"]

    class Connector:
        async def get_current_user_principals(self):
            return ["u:gdrive:t:user"]

        async def get_current_user_group_roles(self):
            return ["g:gdrive:t:engineering"]

    class ConnectorService:
        def __init__(self, connection_manager):
            self.connection_manager = connection_manager

        async def get_connector(self, connection_id):
            assert connection_id == "drive-1"
            return Connector()

    class Indices:
        async def exists(self, index):
            assert index == "openrag_dls_principals"
            return True

    class OpenSearchClient:
        indices = Indices()

        def __init__(self):
            self.index_calls = []

        async def index(self, **kwargs):
            self.index_calls.append(kwargs)

    connection_manager = ConnectionManager()
    opensearch_client = OpenSearchClient()
    service = DLSPrincipalService(
        ConnectorService(connection_manager),
        opensearch_client=opensearch_client,
        refresh_ttl_seconds=60,
    )
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        provider="google",
        opensearch_username="ibmlhapikey_user-1",
    )

    first, second = await asyncio.gather(
        service.refresh_user_principals(user),
        service.refresh_user_principals(user),
    )
    third = await service.refresh_user_principals(user)

    assert first == second == third
    assert "g:gdrive:t:engineering" in first
    assert connection_manager.list_calls == 1
    assert len(opensearch_client.index_calls) == 2
    assert {call["id"] for call in opensearch_client.index_calls} == {
        "ibmlhapikey_user-1",
        "user-1",
    }


@pytest.mark.asyncio
async def test_dls_principal_service_disabled_refresh_cache_does_not_retain_locks():
    from services.dls_principal_service import DLSPrincipalService
    from session_manager import User

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            return []

        def get_auth_user_principals(self, user):
            return [f"u:test:{user.user_id}"]

    class ConnectorService:
        connection_manager = ConnectionManager()

    class Indices:
        async def exists(self, index):
            return True

    class OpenSearchClient:
        indices = Indices()

        def __init__(self):
            self.index_calls = []

        async def index(self, **kwargs):
            self.index_calls.append(kwargs)

    opensearch_client = OpenSearchClient()
    service = DLSPrincipalService(
        ConnectorService(),
        opensearch_client=opensearch_client,
        refresh_ttl_seconds=0,
    )

    for user_id in ("user-1", "user-2"):
        principals = await service.refresh_user_principals(
            User(user_id=user_id, email=None, name=None, provider="test")
        )
        assert principals == [f"u:test:{user_id}"]

    assert len(opensearch_client.index_calls) == 2
    assert service._cache == {}
    assert service._locks == {}


@pytest.mark.asyncio
async def test_dls_principal_service_skips_connector_lookup_without_opensearch_client(monkeypatch):
    from services.dls_principal_service import DLSPrincipalService
    from session_manager import User

    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", True)
    monkeypatch.setattr("config.settings.OPENSEARCH_PASSWORD", "")

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            raise AssertionError("connector lookup should not run without an OpenSearch client")

    class ConnectorService:
        connection_manager = ConnectionManager()

    service = DLSPrincipalService(
        ConnectorService(),
        opensearch_client=None,
        refresh_ttl_seconds=60,
    )

    principals = await service.refresh_user_principals(
        User(
            user_id="user-1",
            email="user@example.com",
            name="User",
            provider="google",
        )
    )

    assert principals == []


def test_dls_principal_service_uses_basic_admin_client_in_ibm(monkeypatch):
    from services.dls_principal_service import DLSPrincipalService

    class Clients:
        def __init__(self):
            self.calls = []
            self.opensearch = object()

        def create_basic_opensearch_client(self, username, password):
            self.calls.append((username, password))
            return "admin-client"

    clients = Clients()
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", True)
    monkeypatch.setattr("config.settings.OPENSEARCH_USERNAME", "admin-user")
    monkeypatch.setattr("config.settings.OPENSEARCH_PASSWORD", "admin-pass")
    monkeypatch.setattr("config.settings.clients", clients)

    service = DLSPrincipalService(connector_service=None)

    assert service._get_opensearch_client() == "admin-client"
    assert service._get_opensearch_client() == "admin-client"
    assert clients.calls == [("admin-user", "admin-pass")]


@pytest.mark.asyncio
async def test_opensearch_init_adds_missing_acl_keyword_mappings():
    from utils.opensearch_init import _ensure_keyword_mappings

    class Indices:
        def __init__(self):
            self.put_mapping_calls = []

        async def get_mapping(self, index):
            assert index == "documents"
            return {
                "documents": {
                    "mappings": {
                        "properties": {
                            "allowed_users": {"type": "keyword"},
                            "allowed_groups": {"type": "keyword"},
                        }
                    }
                }
            }

        async def put_mapping(self, **kwargs):
            self.put_mapping_calls.append(kwargs)

    class OpenSearchClient:
        def __init__(self):
            self.indices = Indices()

    opensearch_client = OpenSearchClient()

    await _ensure_keyword_mappings(
        opensearch_client,
        "documents",
        ["allowed_users", "allowed_groups", "allowed_principals"],
    )

    assert opensearch_client.indices.put_mapping_calls == [
        {
            "index": "documents",
            "body": {"properties": {"allowed_principals": {"type": "keyword"}}},
        }
    ]


@pytest.mark.asyncio
async def test_connector_service_mints_plain_jwt_when_session_user_is_missing(
    monkeypatch,
):
    from session_manager import SessionManager

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class Connector:
        async def get_current_user_group_roles(self):
            return ["g:test:t:g1"]

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            assert user_id == "stored-user-id"
            return [Connection("connection-1", "custom")]

        async def get_connector(self, connection_id):
            assert connection_id == "connection-1"
            return Connector()

    session_manager = SessionManager("test")
    from connectors.service import ConnectorService

    service = ConnectorService(
        patched_async_client=None,
        embed_model="test",
        index_name="test-index",
        session_manager=session_manager,
    )

    service.connection_manager = ConnectionManager()

    token = await service._get_effective_sync_jwt("stored-user-id")
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["sub"] == "stored-user-id"
    assert payload["roles"] == ["openrag_user"]


def test_google_drive_file_acl_group_is_canonicalized(tmp_path):
    from connectors.google_drive.connector import GoogleDriveConnector
    from connectors.google_drive_acl import google_drive_group_role, google_drive_user_principal

    class Execute:
        def execute(self):
            return {
                "permissions": [
                    {
                        "type": "group",
                        "role": "reader",
                        "emailAddress": "Engineering@example.com",
                    },
                    {
                        "type": "user",
                        "role": "owner",
                        "emailAddress": "owner@example.com",
                    },
                ]
            }

    class Permissions:
        def list(self, **kwargs):
            assert kwargs["fileId"] == "file-1"
            return Execute()

    class Service:
        def permissions(self):
            return Permissions()

    connector = GoogleDriveConnector(
        {
            "client_id": "client",
            "client_secret": "secret",
            "token_file": str(tmp_path / "token.json"),
        }
    )
    connector.service = Service()

    acl = connector._extract_google_drive_acl({"id": "file-1"})

    assert acl.owner == "owner@example.com"
    assert acl.allowed_users == ["owner@example.com"]
    assert acl.allowed_groups == [google_drive_group_role("engineering@example.com")]
    assert acl.allowed_principals == [
        google_drive_group_role("engineering@example.com"),
        google_drive_user_principal("owner@example.com"),
    ]
    assert acl.allowed_principal_labels == [
        {
            "principal": google_drive_group_role("engineering@example.com"),
            "kind": "group",
            "provider": "gdrive",
            "display_name": "Engineering@example.com",
            "email": "Engineering@example.com",
            "external_id": "Engineering@example.com",
        },
        {
            "principal": google_drive_user_principal("owner@example.com"),
            "kind": "user",
            "provider": "gdrive",
            "display_name": "owner@example.com",
            "email": "owner@example.com",
            "external_id": "owner@example.com",
        },
    ]


def test_connection_manager_resolves_auth_user_principals(tmp_path):
    from connectors.connection_manager import ConnectionManager
    from connectors.google_drive_acl import google_drive_user_principal
    from session_manager import User

    manager = ConnectionManager(connections_file=str(tmp_path / "connections.json"))

    assert manager.get_auth_user_principals(
        User(
            user_id="google-subject",
            email="user@example.com",
            name="User",
            provider="google",
        )
    ) == [google_drive_user_principal("user@example.com")]


@pytest.mark.asyncio
async def test_google_drive_group_roles_use_directory_groups(monkeypatch):
    from connectors.google_drive_acl import (
        get_current_user_google_group_roles,
        google_drive_group_role,
    )

    class Credentials:
        id_token = jwt.encode(
            {"email": "user@example.com"},
            "google-test-secret-with-32-bytes",
            algorithm="HS256",
        )

    class Execute:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class Groups:
        def list(self, **kwargs):
            assert kwargs["userKey"] == "user@example.com"
            assert kwargs["domain"] == "example.com"
            assert "customer" not in kwargs
            return Execute(
                {
                    "groups": [
                        {"email": "Engineering@example.com"},
                        {"email": "Security@example.com"},
                    ]
                }
            )

    class DirectoryService:
        def groups(self):
            return Groups()

    def fake_build(*args, **kwargs):
        if args[:2] == ("cloudidentity", "v1"):
            raise RuntimeError("Cloud Identity unavailable")
        assert args[:2] == ("admin", "directory_v1")
        return DirectoryService()

    monkeypatch.setattr("connectors.google_drive_acl.build", fake_build)

    roles = await get_current_user_google_group_roles(
        drive_service=None,
        credentials=Credentials(),
    )

    assert roles == [
        google_drive_group_role("engineering@example.com"),
        google_drive_group_role("security@example.com"),
    ]


@pytest.mark.asyncio
async def test_google_drive_group_roles_prefer_cloud_identity(monkeypatch):
    from connectors.google_drive_acl import (
        get_current_user_google_group_roles,
        google_drive_group_role,
    )

    class Credentials:
        id_token = jwt.encode(
            {"email": "user@example.com"},
            "google-test-secret-with-32-bytes",
            algorithm="HS256",
        )

    class Execute:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class Memberships:
        def searchTransitiveGroups(self, **kwargs):
            assert kwargs["parent"] == "groups/-"
            assert "member_key_id == 'user@example.com'" in kwargs["query"]
            return Execute(
                {
                    "memberships": [
                        {"groupKey": {"id": "Engineering@example.com"}},
                        {"groupKey": {"id": "Security@example.com"}},
                    ]
                }
            )

    class Groups:
        def memberships(self):
            return Memberships()

    class CloudIdentityService:
        def groups(self):
            return Groups()

    def fake_build(*args, **kwargs):
        assert args[:2] == ("cloudidentity", "v1")
        return CloudIdentityService()

    monkeypatch.setattr("connectors.google_drive_acl.build", fake_build)

    roles = await get_current_user_google_group_roles(
        drive_service=None,
        credentials=Credentials(),
    )

    assert roles == [
        google_drive_group_role("engineering@example.com"),
        google_drive_group_role("security@example.com"),
    ]
