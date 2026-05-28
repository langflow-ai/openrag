"""ensure_user_row with jwt_roles: JWT is authoritative.

Verifies:
* Brand-new user with jwt_roles=["admin"] becomes admin.
* Existing user re-syncs roles on subsequent calls: revokes roles the JWT
  no longer carries, adds new ones.
* jwt_roles=None falls back to the env default role (no bootstrap-admin);
  the anonymous user gets OPENRAG_NOAUTH_ROLE.
* Unknown role names in the JWT are skipped (logged, not assigned).
"""

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
from services.user_service import ensure_user_row, sync_jwt_roles  # noqa: E402
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


def _user(uid="u1", email="a@example.com", name="A", provider="ibm_ams"):
    return User(user_id=uid, email=email, name=name, provider=provider)


@pytest.mark.asyncio
async def test_new_user_with_jwt_roles_skips_bootstrap(session):
    """JWT-sourced role: first user gets exactly what the JWT says, not
    the bootstrap admin shortcut."""
    row = await ensure_user_row(session, _user(uid="oauth-1"), jwt_roles=["user"])
    await session.commit()

    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"user"}, "bootstrap-admin must not fire when JWT roles supplied"


@pytest.mark.asyncio
async def test_new_user_with_jwt_admin_becomes_admin(session):
    row = await ensure_user_row(session, _user(uid="oauth-1"), jwt_roles=["admin"])
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}


@pytest.mark.asyncio
async def test_existing_user_role_set_reconciled_on_relogin(session):
    """Login 1: admin+user. Login 2: just user. Admin is revoked."""
    user = _user(uid="oauth-1")
    row = await ensure_user_row(session, user, jwt_roles=["admin", "user"])
    await session.commit()
    assert {r.name for r in await RoleRepo(session).list_user_roles(row.id)} == {
        "admin",
        "user",
    }

    # Second login — JWT now carries only "user"
    again = await ensure_user_row(session, user, jwt_roles=["user"])
    await session.commit()
    assert again.id == row.id
    assert {r.name for r in await RoleRepo(session).list_user_roles(row.id)} == {"user"}


@pytest.mark.asyncio
async def test_jwt_roles_none_assigns_default_role(session, monkeypatch):
    """When jwt_roles is None, the user gets OPENRAG_DEFAULT_ROLE — there is
    no first-user-becomes-admin bootstrap."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    row = await ensure_user_row(session, _user(uid="oauth-1"))
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"user"}


@pytest.mark.asyncio
async def test_anonymous_user_gets_noauth_role(session, monkeypatch):
    """The synthetic anonymous user gets OPENRAG_NOAUTH_ROLE (default admin)."""
    monkeypatch.setenv("OPENRAG_NOAUTH_ROLE", "admin")
    row = await ensure_user_row(
        session, _user(uid="anonymous", email="anonymous@localhost", provider="none")
    )
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}


@pytest.mark.asyncio
async def test_unknown_role_names_skipped(session):
    """JWT carrying a role that doesn't exist in the roles table is ignored."""
    row = await ensure_user_row(session, _user(uid="oauth-1"), jwt_roles=["admin", "nonexistent"])
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}


@pytest.mark.asyncio
async def test_sync_jwt_roles_standalone(session, monkeypatch):
    """The public sync_jwt_roles entry point reconciles without creating
    the user row — covers the dependency-cache fast path."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    # Pre-create a user with the env default role.
    row = await ensure_user_row(session, _user(uid="oauth-1"))
    await session.commit()
    assert {r.name for r in await RoleRepo(session).list_user_roles(row.id)} == {"user"}

    # Now reconcile to "admin" through the standalone helper.
    await sync_jwt_roles(session, row.id, ["admin"])
    await session.commit()
    assert {r.name for r in await RoleRepo(session).list_user_roles(row.id)} == {"admin"}


@pytest.mark.asyncio
async def test_rbac_off_with_no_claim_assigns_default_role(session, monkeypatch):
    """Regression: when RBAC is disabled and the IBM JWT carries no roles
    claim, ``_get_ibm_user`` leaves jwt_roles=None so ensure_user_row falls
    back to the env default role (no bootstrap-admin). Verified here by
    passing jwt_roles=None — what the auth handler sets when
    jwt_roles_enabled() returns False."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    row = await ensure_user_row(session, _user(uid="oauth-1"), jwt_roles=None)
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"user"}, "RBAC-off path assigns the env default role"


@pytest.mark.asyncio
async def test_empty_jwt_roles_list_revokes_all(session):
    """JWT-side decision: an explicit empty list (caller chose to pass it
    through) revokes every role. (In practice _get_ibm_user 401s before
    reaching this code path when the list is empty and RBAC is enforced.)"""
    user = _user(uid="oauth-1")
    row = await ensure_user_row(session, user, jwt_roles=["admin"])
    await session.commit()
    assert {r.name for r in await RoleRepo(session).list_user_roles(row.id)} == {"admin"}

    await ensure_user_row(session, user, jwt_roles=[])
    await session.commit()
    assert await RoleRepo(session).list_user_roles(row.id) == []
