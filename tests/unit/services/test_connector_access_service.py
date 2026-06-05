"""Connector access policy helpers."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from services.connector_access_service import (  # noqa: E402
    CONNECTOR_TYPES,
    filter_connectors_for_user,
    get_access_map,
    is_connector_allowed,
    set_connector_access_bulk,
)


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


@pytest.mark.asyncio
async def test_filter_connectors_hides_disabled_types_for_non_admin(session):
    metadata = {
        "google_drive": {"name": "Google Drive"},
        "sharepoint": {"name": "SharePoint"},
        "onedrive": {"name": "OneDrive"},
    }
    access_map = {
        "google_drive": False,
        "sharepoint": True,
        "onedrive": False,
    }

    filtered = filter_connectors_for_user(metadata, access_map, is_admin=False)

    assert set(filtered.keys()) == {"sharepoint"}


@pytest.mark.asyncio
async def test_filter_connectors_admin_sees_all(session):
    metadata = {
        "google_drive": {"name": "Google Drive"},
        "sharepoint": {"name": "SharePoint"},
    }
    access_map = {"google_drive": False, "sharepoint": True}

    filtered = filter_connectors_for_user(metadata, access_map, is_admin=True)

    assert filtered == metadata


@pytest.mark.asyncio
async def test_is_connector_allowed_reads_workspace_config(session):
    await WorkspaceConfigRepo(session).upsert(
        "connector_access",
        {"google_drive": False, "sharepoint": True},
    )
    await session.commit()

    access = await get_access_map(session)
    assert access["google_drive"] is False
    assert await is_connector_allowed(session, "sharepoint") is True
    assert await is_connector_allowed(session, "google_drive") is False


@pytest.mark.asyncio
async def test_connector_types_derived_from_registry(session):
    # Single source of truth: the policy module mirrors the connector registry.
    from connectors.connection_manager import CONNECTOR_TYPE_KEYS

    assert CONNECTOR_TYPES == CONNECTOR_TYPE_KEYS
    assert "google_drive" in CONNECTOR_TYPES


@pytest.mark.asyncio
async def test_set_connector_access_bulk_persists(session):
    await set_connector_access_bulk(session, {"google_drive": False}, actor_user_id="u1")
    await session.commit()

    assert await is_connector_allowed(session, "google_drive") is False
    # Untouched types stay enabled by default.
    assert await is_connector_allowed(session, "sharepoint") is True


@pytest.mark.asyncio
async def test_set_connector_access_bulk_rejects_unknown_type(session):
    with pytest.raises(ValueError, match="Unknown connector type"):
        await set_connector_access_bulk(session, {"not_a_connector": True}, actor_user_id="u1")
