"""Tests for env-driven default role sync."""

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
from db.repositories import RoleRepo, WorkspaceConfigRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from services.default_role_sync import sync_default_roles_if_changed  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        await s.commit()
        yield s
    await engine.dispose()


def _user(uid: str) -> User:
    return User(user_id=uid, email=f"{uid}@example.com", name=uid, provider="google")


@pytest.mark.asyncio
async def test_sync_skipped_outside_oss(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await session.commit()

    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    result = await sync_default_roles_if_changed(session)
    roles = await RoleRepo(session).list_user_roles(user_row.id)

    assert result.enabled is False
    assert result.updated_users == 0
    assert [r.name for r in roles] == ["user"]


@pytest.mark.asyncio
async def test_sync_disabled_is_noop(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "false")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    row = await ensure_user_row(session, _user("u1"))
    await session.commit()

    result = await sync_default_roles_if_changed(session, enabled=False)
    roles = await RoleRepo(session).list_user_roles(row.id)

    assert result.updated_users == 0
    assert [r.name for r in roles] == ["user"]


@pytest.mark.asyncio
async def test_first_run_with_unchanged_env_records_baseline(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await session.commit()

    result = await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)
    meta = await WorkspaceConfigRepo(session).get_section("meta")

    assert result.baseline_recorded is True
    assert result.updated_users == 0
    assert [r.name for r in roles] == ["user"]
    assert meta["rbac_default_role_sync"]["default_role"] == "user"


@pytest.mark.asyncio
async def test_first_run_migrates_from_implicit_user_default(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await session.commit()

    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    result = await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)
    meta = await WorkspaceConfigRepo(session).get_section("meta")

    assert result.updated_users == 1
    assert [r.name for r in roles] == ["admin"]
    assert meta["rbac_default_role_sync"]["default_role"] == "admin"


@pytest.mark.asyncio
async def test_from_role_overrides_wrong_baseline(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await session.commit()

    meta_repo = WorkspaceConfigRepo(session)
    await meta_repo.upsert(
        "meta",
        {"rbac_default_role_sync": {"default_role": "admin", "noauth_role": "admin"}},
    )
    await session.commit()

    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    result = await sync_default_roles_if_changed(session, enabled=True, from_role="user")
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)
    assert result.updated_users == 1
    assert [r.name for r in roles] == ["admin"]


@pytest.mark.asyncio
async def test_env_change_updates_single_role_users(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    result = await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)

    assert result.updated_users == 1
    assert [r.name for r in roles] == ["admin"]


@pytest.mark.asyncio
async def test_skips_multi_role_users(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    role_repo = RoleRepo(session)
    dev_role = await role_repo.get_by_name("developer")
    await role_repo.assign_role(user_row.id, dev_role.id)
    await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    result = await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)

    assert result.updated_users == 0
    assert result.skipped_users == 1
    assert {r.name for r in roles} == {"user", "developer"}


@pytest.mark.asyncio
async def test_explicit_to_role_overrides_env(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    user_row = await ensure_user_row(session, _user("u1"))
    role_repo = RoleRepo(session)
    user_role = await role_repo.get_by_name("user")
    admin_role = await role_repo.get_by_name("admin")
    await role_repo.revoke_role(user_row.id, user_role.id)
    await role_repo.assign_role(user_row.id, admin_role.id)
    await WorkspaceConfigRepo(session).upsert(
        "meta",
        {"rbac_default_role_sync": {"default_role": "admin", "noauth_role": "admin"}},
    )
    await session.commit()

    result = await sync_default_roles_if_changed(
        session, enabled=True, from_role="admin", to_role="user"
    )
    await session.commit()

    roles = await RoleRepo(session).list_user_roles(user_row.id)
    assert result.updated_users == 1
    assert [r.name for r in roles] == ["user"]


@pytest.mark.asyncio
async def test_dry_run_does_not_write(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_SYNC_DEFAULT_ROLE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    user_row = await ensure_user_row(session, _user("u1"))
    await sync_default_roles_if_changed(session, enabled=True)
    await session.commit()

    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "viewer")
    result = await sync_default_roles_if_changed(session, enabled=True, dry_run=True)

    roles = await RoleRepo(session).list_user_roles(user_row.id)
    meta = await WorkspaceConfigRepo(session).get_section("meta")

    assert result.updated_users == 1
    assert [r.name for r in roles] == ["user"]
    assert meta is None or meta.get("rbac_default_role_sync", {}).get("default_role") == "user"
