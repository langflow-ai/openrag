"""migrations_runtime.run — RBAC catalog sync on startup."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.migrations_runtime import (  # noqa: E402
    CHAT_HISTORY_JSON_TO_DB_V1,
    CONFIG_YAML_TO_DB_V1,
    JSON_TO_DB_V1,
    _already_done,
    _mark_done,
    run,
)
from db.models import Permission, Role, RolePermission  # noqa: E402
from db.seed import (  # noqa: E402
    permission_name,
    seed_roles_and_permissions,
)

_MANAGE_ACCESS = permission_name("connectors", "manage:access")


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
        yield s
    await engine.dispose()


async def _skip_legacy_runtime_migrations(session) -> None:
    for name in (JSON_TO_DB_V1, CONFIG_YAML_TO_DB_V1, CHAT_HISTORY_JSON_TO_DB_V1):
        if not await _already_done(session, name):
            await _mark_done(session, name)


async def _remove_manage_access(session) -> None:
    perm = (
        await session.execute(select(Permission).where(Permission.name == _MANAGE_ACCESS))
    ).scalar_one()
    await session.execute(delete(RolePermission).where(RolePermission.permission_id == perm.id))
    await session.execute(delete(Permission).where(Permission.id == perm.id))
    await session.flush()


@pytest.mark.asyncio
async def test_run_backfills_missing_manage_access_permission(session):
    await seed_roles_and_permissions(session)
    await _remove_manage_access(session)
    await session.commit()

    assert (
        await session.execute(select(Permission).where(Permission.name == _MANAGE_ACCESS))
    ).scalar_one_or_none() is None

    await _skip_legacy_runtime_migrations(session)
    await run(session)
    await session.commit()

    perm = (
        await session.execute(select(Permission).where(Permission.name == _MANAGE_ACCESS))
    ).scalar_one()
    admin = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    grant = (
        await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == admin.id,
                RolePermission.permission_id == perm.id,
            )
        )
    ).scalar_one_or_none()
    assert grant is not None


@pytest.mark.asyncio
async def test_run_rbac_catalog_sync_is_idempotent(session):
    await seed_roles_and_permissions(session)
    await _remove_manage_access(session)
    await session.commit()

    perm_count = len((await session.execute(select(Permission))).scalars().all())
    rp_count = len((await session.execute(select(RolePermission))).scalars().all())

    await _skip_legacy_runtime_migrations(session)
    await run(session)
    await session.commit()
    await run(session)
    await session.commit()

    assert len((await session.execute(select(Permission))).scalars().all()) == perm_count + 1
    assert len((await session.execute(select(RolePermission))).scalars().all()) == rp_count + 1
