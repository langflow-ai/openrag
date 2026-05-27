"""ensure_user_row: every user gets the env default role (no bootstrap-admin)."""

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


def _user(uid="u1", email="a@example.com", name="A", provider="google"):
    return User(user_id=uid, email=email, name=name, provider=provider)


@pytest.mark.asyncio
async def test_first_user_gets_default_role(session, monkeypatch):
    """No bootstrap-admin: even the first user gets the env default role."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    row = await ensure_user_row(session, _user(uid="oauth-1"))
    await session.commit()

    role_repo = RoleRepo(session)
    roles = await role_repo.list_user_roles(row.id)
    assert {r.name for r in roles} == {"user"}


@pytest.mark.asyncio
async def test_all_users_get_default_role(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    first = await ensure_user_row(session, _user(uid="oauth-1", email="a@x.com"))
    second = await ensure_user_row(session, _user(uid="oauth-2", email="b@x.com"))
    await session.commit()

    role_repo = RoleRepo(session)
    first_roles = {r.name for r in await role_repo.list_user_roles(first.id)}
    second_roles = {r.name for r in await role_repo.list_user_roles(second.id)}
    assert first_roles == {"user"}
    assert second_roles == {"user"}


@pytest.mark.asyncio
async def test_default_role_is_configurable(session, monkeypatch):
    """An oss operator who wants an admin sets OPENRAG_DEFAULT_ROLE=admin."""
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "admin")
    row = await ensure_user_row(session, _user(uid="oauth-1"))
    await session.commit()
    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}


@pytest.mark.asyncio
async def test_repeated_calls_are_idempotent(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    a = await ensure_user_row(session, _user(uid="oauth-1"))
    b = await ensure_user_row(session, _user(uid="oauth-1"))
    await session.commit()

    assert a.id == b.id
    role_repo = RoleRepo(session)
    roles = await role_repo.list_user_roles(a.id)
    assert {r.name for r in roles} == {"user"}


@pytest.mark.asyncio
async def test_new_user_id_matches_oauth_subject(session):
    """Regression: the SQL users.id must equal the OAuth subject so
    require_permission can use the JWT sub directly (no extra lookup)."""
    row = await ensure_user_row(session, _user(uid="oauth-subject-xyz", email="z@x.com"))
    await session.commit()
    assert row.id == "oauth-subject-xyz"
    assert row.oauth_subject == "oauth-subject-xyz"


@pytest.mark.asyncio
async def test_legacy_user_merges_on_real_signin(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    # Pre-seed an existing user; the legacy merge below should still get the
    # env default role, not anything special.
    await ensure_user_row(session, _user(uid="oauth-admin", email="root@x.com"))
    await session.commit()

    # Pretend a JSON migration inserted a legacy row keyed by a GA user_id.
    from db.models import User as UserRow
    from db.repositories._helpers import email_lookup_hash

    legacy = UserRow(
        id="legacy-123",
        oauth_provider="legacy",
        oauth_subject="legacy-123",
        email="alice@example.com",
        email_lookup_hash=email_lookup_hash("alice@example.com"),
        display_name="alice (legacy)",
    )
    session.add(legacy)
    await session.commit()

    merged = await ensure_user_row(
        session,
        User(user_id="legacy-123", email="alice@example.com", name="Alice", provider="google"),
    )
    await session.commit()

    assert merged.id == "legacy-123", "user_id must be preserved across merge"
    assert merged.oauth_provider == "google"
    assert merged.oauth_subject == "legacy-123"

    role_repo = RoleRepo(session)
    roles = {r.name for r in await role_repo.list_user_roles(merged.id)}
    assert roles == {"user"}
