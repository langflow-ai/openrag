"""auth_init must enforce workspace connector policy for all callers."""

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
from api.auth import AuthInitBody, auth_init  # noqa: E402
from db.repositories import WorkspaceConfigRepo  # noqa: E402


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
    headers: dict[str, str] = {}


@pytest.mark.asyncio
async def test_auth_init_blocks_disabled_connector_without_user(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False},
    )
    await session.commit()

    auth_service = AsyncMock()
    body = AuthInitBody(connector_type="google_drive", purpose="data_source")

    response = await auth_init(
        body,
        _FakeRequest(),
        auth_service=auth_service,
        user=None,
        session=session,
    )

    assert response.status_code == 403
    assert "google_drive" in json.loads(response.body)["error"]
    auth_service.init_oauth.assert_not_called()


@pytest.mark.asyncio
async def test_auth_init_allows_disabled_connector_when_policy_not_enforced(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False},
    )
    await session.commit()

    auth_service = AsyncMock()
    auth_service.init_oauth = AsyncMock(return_value={"auth_url": "https://example.com"})
    body = AuthInitBody(
        connector_type="google_drive",
        purpose="data_source",
        redirect_uri="http://localhost/callback",
    )

    response = await auth_init(
        body,
        _FakeRequest(),
        auth_service=auth_service,
        user=None,
        session=session,
    )

    assert response.status_code == 200
    auth_service.init_oauth.assert_called_once()
