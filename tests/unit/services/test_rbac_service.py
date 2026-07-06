"""RBACService — caching, invalidation, and role-override behavior."""

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
from db.seed import seed_roles_and_permissions  # noqa: E402
from services.rbac_service import RBACService  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402


@pytest_asyncio.fixture
async def setup(monkeypatch):
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        admin_user = await ensure_user_row(
            s, User(user_id="admin-sub", email="admin@x.com", name="A", provider="google")
        )
        # No bootstrap-admin anymore — grant admin explicitly.
        role_repo = RoleRepo(s)
        admin_role = await role_repo.get_by_name("admin")
        await role_repo.assign_role(admin_user.id, admin_role.id)
        end_user = await ensure_user_row(
            s, User(user_id="user-sub", email="u@x.com", name="U", provider="google")
        )
        await s.commit()

    yield SessionLocal, admin_user.id, end_user.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_has_all_perms(setup):
    SessionLocal, admin_id, _ = setup
    rbac = RBACService(SessionLocal)
    perms = await rbac.get_user_permissions(admin_id)
    # admin gets everything in the catalog
    assert "config:write" in perms
    assert "users:list" in perms
    assert "agent:prompt:global" in perms
    assert "connectors:manage:access" in perms


@pytest.mark.asyncio
async def test_connectors_manage_access_is_admin_only(setup):
    SessionLocal, _, user_id = setup
    rbac = RBACService(SessionLocal)

    # Default "user" role lacks it.
    user_perms = await rbac.get_user_permissions(user_id)
    assert "connectors:manage:access" not in user_perms

    # developer and viewer lack it too (checked via role override).
    async with SessionLocal() as s:
        role_repo = RoleRepo(s)
        developer_role = await role_repo.get_by_name("developer")
        viewer_role = await role_repo.get_by_name("viewer")

    dev_perms = await rbac.get_user_permissions(user_id, role_override=[developer_role.id])
    viewer_perms = await rbac.get_user_permissions(user_id, role_override=[viewer_role.id])
    assert "connectors:manage:access" not in dev_perms
    assert "connectors:manage:access" not in viewer_perms


@pytest.mark.asyncio
async def test_default_user_lacks_admin_perms(setup):
    SessionLocal, _, user_id = setup
    rbac = RBACService(SessionLocal)
    perms = await rbac.get_user_permissions(user_id)
    assert "chat:use" in perms
    assert "config:write" not in perms
    assert "users:list" not in perms


@pytest.mark.asyncio
async def test_cache_invalidation_picks_up_new_role(setup):
    SessionLocal, _, user_id = setup
    rbac = RBACService(SessionLocal)

    perms_before = await rbac.get_user_permissions(user_id)
    assert "users:list" not in perms_before

    # Promote to admin out-of-band
    async with SessionLocal() as s:
        role_repo = RoleRepo(s)
        admin_role = await role_repo.get_by_name("admin")
        await role_repo.assign_role(user_id, admin_role.id)
        await s.commit()

    # Stale cache: still no admin perms
    perms_stale = await rbac.get_user_permissions(user_id)
    assert "users:list" not in perms_stale

    rbac.invalidate(user_id)

    perms_after = await rbac.get_user_permissions(user_id)
    assert "users:list" in perms_after


@pytest.mark.asyncio
async def test_role_override_bypasses_cache(setup):
    SessionLocal, admin_id, user_id = setup
    rbac = RBACService(SessionLocal)

    # Warm cache
    await rbac.get_user_permissions(admin_id)

    async with SessionLocal() as s:
        role_repo = RoleRepo(s)
        viewer_role = await role_repo.get_by_name("viewer")

    perms = await rbac.get_user_permissions(admin_id, role_override=[viewer_role.id])
    assert "config:write" not in perms
    assert "chat:use" in perms
