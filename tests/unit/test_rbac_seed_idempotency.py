"""Verify db.seed.seed_roles_and_permissions is idempotent."""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401  (registers tables)
from db.models import Permission, Role, RolePermission  # noqa: E402
from db.seed import (  # noqa: E402
    BUILTIN_ROLES,
    PERMISSIONS,
    ROLE_PERMISSION_MAP,
    seed_roles_and_permissions,
)


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


@pytest.mark.asyncio
async def test_seed_creates_expected_rows(session):
    await seed_roles_and_permissions(session)
    await session.commit()

    perms = (await session.execute(select(Permission))).scalars().all()
    roles = (await session.execute(select(Role))).scalars().all()

    assert len(perms) == len(PERMISSIONS)
    assert {r.name for r in roles} == {n for _, n, _ in BUILTIN_ROLES}

    # admin gets every permission
    admin_role = next(r for r in roles if r.name == "admin")
    admin_perm_ids = {
        rp.permission_id
        for rp in (await session.execute(select(RolePermission).where(RolePermission.role_id == admin_role.id))).scalars().all()
    }
    assert len(admin_perm_ids) == len(PERMISSIONS)


@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    await seed_roles_and_permissions(session)
    await session.commit()

    perm_count_before = len((await session.execute(select(Permission))).scalars().all())
    role_count_before = len((await session.execute(select(Role))).scalars().all())
    rp_count_before = len((await session.execute(select(RolePermission))).scalars().all())

    # Re-run should not duplicate anything.
    await seed_roles_and_permissions(session)
    await session.commit()

    assert len((await session.execute(select(Permission))).scalars().all()) == perm_count_before
    assert len((await session.execute(select(Role))).scalars().all()) == role_count_before
    assert len((await session.execute(select(RolePermission))).scalars().all()) == rp_count_before


@pytest.mark.asyncio
async def test_role_permission_map_references_known_perms(session):
    await seed_roles_and_permissions(session)
    await session.commit()
    perm_names = {p.name for p in (await session.execute(select(Permission))).scalars().all()}
    for role_name, expected in ROLE_PERMISSION_MAP.items():
        missing = expected - perm_names
        assert not missing, f"role {role_name} references unknown perms: {missing}"
