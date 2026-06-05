"""Connector handlers must enforce workspace connector policy."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

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
)
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from services.connector_access_service import OPENRAG_BRAND_HEADER  # noqa: E402
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
    def __init__(self, brand: str = "ibm"):
        self.headers = {OPENRAG_BRAND_HEADER: brand}
        self.query_params: dict[str, str] = {}


@pytest.fixture
def user():
    return User(user_id="user-1", email="u@example.com", name="User", jwt_token="jwt")


@pytest.mark.asyncio
async def test_connector_disconnect_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False},
    )
    await session.commit()

    connector_service = AsyncMock()
    response = await connector_disconnect(
        "google_drive",
        _FakeRequest("ibm"),
        connector_service=connector_service,
        user=user,
        session=session,
    )

    assert response.status_code == 403
    assert "google_drive" in json.loads(response.body)["error"]
    connector_service.connection_manager.list_connections.assert_not_called()


@pytest.mark.asyncio
async def test_connector_token_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
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
        _FakeRequest("ibm"),
        connector_service=connector_service,
        user=user,
        session=session,
    )

    assert response.status_code == 403
    connector_service.connection_manager.get_connection.assert_not_called()


@pytest.mark.asyncio
async def test_connector_sync_preview_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"sharepoint": False},
    )
    await session.commit()

    response = await connector_sync_preview(
        "sharepoint",
        _FakeRequest("ibm"),
        connector_service=AsyncMock(),
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 403
    assert "sharepoint" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_browse_connection_files_blocks_disabled_type(session, user, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
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
        _FakeRequest("ibm"),
        connector_service=connector_service,
        session_manager=AsyncMock(),
        user=user,
        session=session,
    )

    assert response.status_code == 403
    connector_service.get_connector.assert_not_called()
