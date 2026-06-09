"""dev_role_toggle — generic built-in role switching (testing-only feature)."""

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
from db.repositories import RoleRepo  # noqa: E402
from db.seed import BUILTIN_ROLES, seed_roles_and_permissions  # noqa: E402
from services.dev_role_toggle import _DEV_ROLES, set_dev_role  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402

_TEST_USER = User(user_id="dev-sub", email="dev@x.com", name="D", provider="google")


@pytest_asyncio.fixture
async def setup():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        db_user = await ensure_user_row(s, _TEST_USER)
        role_repo = RoleRepo(s)
        user_role = await role_repo.get_by_name("user")
        await role_repo.assign_role(db_user.id, user_role.id)
        await s.commit()

    yield SessionLocal
    await engine.dispose()


def test_dev_roles_covers_every_builtin_role():
    assert _DEV_ROLES == frozenset(name for _id, name, _desc in BUILTIN_ROLES)
    assert {"admin", "developer", "user", "viewer"} <= _DEV_ROLES


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["admin", "developer", "viewer"])
async def test_switch_to_any_builtin_role(setup, target):
    SessionLocal = setup

    async with SessionLocal() as s:
        roles = await set_dev_role(s, _TEST_USER, target)
        await s.commit()

    assert roles == [target]


@pytest.mark.asyncio
async def test_invalid_role_rejected(setup):
    SessionLocal = setup

    async with SessionLocal() as s:
        with pytest.raises(ValueError, match="Unsupported dev role"):
            await set_dev_role(s, _TEST_USER, "superuser")
