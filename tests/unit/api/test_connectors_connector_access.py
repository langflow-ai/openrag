"""Connector handlers must enforce workspace connector policy."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import db.models  # noqa: E402,F401
from api.connectors import (  # noqa: E402
    browse_connection_files,
    connector_disconnect,
    connector_sync_preview,
    connector_token,
    connector_webhook,
)
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from session_manager import User  # noqa: E402


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class _FakeRequest:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.query_params: dict[str, str] = {}


class _FakeWebhookRequest:
    def __init__(self) -> None:
        self.method = "POST"
        self.headers: dict[str, str] = {}
        self.query_params = {"validationToken": "graph-validation-token"}


@pytest.fixture
def user():
    return User(user_id="user-1", email="u@example.com", name="User", jwt_token="jwt")


@pytest.mark.asyncio
async def test_connector_disconnect_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False},
    )
    await session.commit()

    connector_service = AsyncMock()
    response = await connector_disconnect(
        "google_drive",
        _FakeRequest(),
        connector_service=connector_service,
        user=user,
        session=session,
    )

    assert response.status_code == 403
    assert "google_drive" in json.loads(response.body)["error"]
    connector_service.connection_manager.list_connections.assert_not_called()


@pytest.mark.asyncio
async def test_connector_token_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False},
    )
    await session.commit()

    connector_service = AsyncMock()
    response = await connector_token(
        "google_drive",
        "conn-1",
        _FakeRequest(),
        connector_service=connector_service,
        user=user,
        session=session,
    )

    assert response.status_code == 403
    connector_service.connection_manager.get_connection.assert_not_called()


@pytest.mark.asyncio
async def test_connector_sync_preview_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"sharepoint": False},
    )
    await session.commit()

    response = await connector_sync_preview(
        "sharepoint",
        _FakeRequest(),
        connector_service=AsyncMock(),
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 403
    assert "sharepoint" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_browse_connection_files_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"aws_s3": False},
    )
    await session.commit()

    connector_service = AsyncMock()
    response = await browse_connection_files(
        "aws_s3",
        "conn-1",
        _FakeRequest(),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 403
    connector_service.get_connector.assert_not_called()


@pytest.mark.asyncio
async def test_connector_webhook_blocks_disabled_type_before_validation(session, monkeypatch):
    """Policy must run before validation handshakes for disabled connector types."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"sharepoint": False},
    )
    await session.commit()

    mock_connector = MagicMock()
    mock_connector.handle_webhook_validation.return_value = "graph-validation-token"
    connector_service = AsyncMock()
    connector_service.connection_manager._create_connector.return_value = mock_connector

    response = await connector_webhook(
        "sharepoint",
        _FakeWebhookRequest(),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        session=session,
    )

    assert response.status_code == 403
    assert "sharepoint" in json.loads(response.body)["error"]
    mock_connector.handle_webhook_validation.assert_not_called()
    connector_service.connection_manager._create_connector.assert_not_called()


@pytest.mark.asyncio
async def test_browse_does_not_open_another_users_connection(session, user):
    connector_service = AsyncMock()
    connection = MagicMock(user_id="other-user", connector_type="aws_s3", is_active=True)
    connector_service.connection_manager.get_connection.return_value = connection
    response = await browse_connection_files(
        "aws_s3",
        "another-users-connection",
        _FakeRequest(),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 404
    connector_service.get_connector.assert_not_called()


@pytest.mark.asyncio
async def test_browse_rejects_cross_type_connection(session, user):
    connector_service = AsyncMock()
    connection = MagicMock(user_id=user.user_id, connector_type="google_drive", is_active=True)
    connector_service.connection_manager.get_connection.return_value = connection
    response = await browse_connection_files(
        "aws_s3",
        "wrong-type-connection",
        _FakeRequest(),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 404
    connector_service.get_connector.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_status_never_returns_username_or_internal_origin(
    session, user, monkeypatch
):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "is_plugin_connector_type", lambda value: value == "acme")
    conn = MagicMock()
    conn.connection_id = "conn-1"
    conn.connector_type = "acme"
    conn.user_id = user.user_id
    conn.is_active = True
    conn.name = "Acme"
    conn.created_at = datetime.now()
    conn.last_sync = None
    connector = MagicMock()
    connector.authenticate = AsyncMock(return_value=True)
    connector.get_client_id.return_value = "DOMAIN\\secret-user"
    connector.base_url = "https://internal.example.invalid/"
    service = MagicMock()
    service._get_connector = AsyncMock(return_value=connector)
    service.connection_manager.list_connections = AsyncMock(return_value=[conn])
    service.connection_manager.has_env_credentials.return_value = False

    response = await connectors_api.connector_status(
        "acme",
        _FakeRequest(),
        connector_service=service,
        user=user,
        session=session,
    )
    assert response.status_code == 200
    entry = json.loads(response.body)["connections"][0]
    assert entry["client_id"] is None
    assert entry["base_url"] is None
    connector.get_client_id.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_check_does_not_fall_back_to_another_connection(session, user):
    from api import connectors as connectors_api

    connector_service = AsyncMock()
    connector_service.connection_manager.list_connections.return_value = [
        MagicMock(connection_id="owned", is_active=True)
    ]
    response = await connectors_api.connector_check_duplicates(
        "aws_s3",
        connectors_api.ConnectorCheckDuplicatesBody(
            connection_id="not-owned",
            selected_files=[{"id": "file-1", "name": "report.pdf", "mimeType": "application/pdf"}],
        ),
        _FakeRequest(),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )
    assert response.status_code == 404
    connector_service.get_connector.assert_not_called()
