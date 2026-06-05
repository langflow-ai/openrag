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
    OPENRAG_BRAND_HEADER,
    filter_connectors_for_user,
    get_access_map,
    is_connector_access_policy_enforced,
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
async def test_filter_connectors_applies_workspace_policy_to_all_roles(session):
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

    filtered = filter_connectors_for_user(metadata, access_map)

    assert set(filtered.keys()) == {"sharepoint"}


@pytest.mark.asyncio
async def test_filter_connectors_admin_subject_to_same_policy(session):
    metadata = {
        "google_drive": {"name": "Google Drive"},
        "sharepoint": {"name": "SharePoint"},
    }
    access_map = {"google_drive": False, "sharepoint": True}

    filtered = filter_connectors_for_user(metadata, access_map)

    assert set(filtered.keys()) == {"sharepoint"}


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
    from connectors.registry import get_connector_classes

    registry_types = tuple(cls.CONNECTOR_TYPE for cls in get_connector_classes())
    assert CONNECTOR_TYPES == registry_types
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


class _FakeRequest:
    def __init__(self, brand: str = ""):
        self.headers = {OPENRAG_BRAND_HEADER: brand} if brand else {}


def test_connector_access_policy_enforced_in_saas_run_mode(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setenv("IBM_AUTH_ENABLED", "false")
    assert is_connector_access_policy_enforced() is True
    assert is_connector_access_policy_enforced(_FakeRequest("oss")) is True


def test_connector_access_policy_enforced_with_ibm_auth(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("IBM_AUTH_ENABLED", "true")
    assert is_connector_access_policy_enforced() is True
    assert is_connector_access_policy_enforced(_FakeRequest("oss")) is True


def test_connector_access_policy_oss_run_mode_follows_dev_brand(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("IBM_AUTH_ENABLED", "false")

    assert is_connector_access_policy_enforced(_FakeRequest("ibm")) is True
    assert is_connector_access_policy_enforced(_FakeRequest("oss")) is False
    assert is_connector_access_policy_enforced(_FakeRequest()) is False
    assert is_connector_access_policy_enforced() is False
