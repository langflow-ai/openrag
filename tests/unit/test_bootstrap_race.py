"""First-admin bootstrap must yield exactly one admin even under
concurrent first-sign-ins.

Two `ensure_user_row` calls fired with `asyncio.gather` against an empty
DB: both observe `count_admins == 0`, both attempt to grant admin. The
post-grant rollback (lexicographic tie-break) must demote the loser
before either request returns.
"""

import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await seed_roles_and_permissions(s)
        await s.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_race_yields_single_admin(session_factory):
    """Two concurrent first-sign-ins → exactly one admin.

    Each call uses its own session (mirrors what FastAPI does per
    request). The post-grant rollback must observe the second admin
    and demote whichever caller is not min(user_id).
    """
    async def signin(user_id: str) -> None:
        async with session_factory() as session:
            await ensure_user_row(
                session,
                User(
                    user_id=user_id,
                    email=f"{user_id}@x.com",
                    name=user_id,
                    provider="google",
                ),
            )
            await session.commit()

    # SQLite serializes writes, so true parallelism is limited; but the
    # service does several reads/writes per call, so even on SQLite the
    # interleaving exercises the rollback branch.
    await asyncio.gather(signin("alice"), signin("bob"))

    async with session_factory() as session:
        admins = await RoleRepo(session).list_admin_user_ids()

    assert len(admins) == 1, f"expected 1 admin, got {admins}"
    # Lexicographic min wins
    assert admins[0] == "alice"


@pytest.mark.asyncio
async def test_bootstrap_loser_falls_through_to_default_role(session_factory):
    """The demoted bootstrap loser must still end up with the default
    role, not zero roles."""
    async def signin(user_id: str) -> None:
        async with session_factory() as session:
            await ensure_user_row(
                session,
                User(
                    user_id=user_id,
                    email=f"{user_id}@x.com",
                    name=user_id,
                    provider="google",
                ),
            )
            await session.commit()

    await asyncio.gather(signin("alice"), signin("zach"))

    async with session_factory() as session:
        repo = RoleRepo(session)
        admins = await repo.list_admin_user_ids()
        zach_roles = await repo.list_user_roles("zach")

    assert admins == ["alice"]
    role_names = {r.name for r in zach_roles}
    # Default role is "user" (set by OPENRAG_DEFAULT_ROLE, default "user")
    assert "user" in role_names, f"loser should have default role, got {role_names}"
    assert "admin" not in role_names


@pytest.mark.asyncio
async def test_no_race_single_signin_unchanged(session_factory):
    """Sanity check — when there's no race, the first user becomes admin."""
    async with session_factory() as session:
        await ensure_user_row(
            session,
            User(user_id="solo", email="s@x", name="S", provider="google"),
        )
        await session.commit()
    async with session_factory() as session:
        admins = await RoleRepo(session).list_admin_user_ids()
    assert admins == ["solo"]


@pytest.mark.asyncio
async def test_concurrent_signins_same_user_no_integrity_error(
    session_factory, monkeypatch
):
    """Five concurrent `_ensure_db_user` calls for the SAME anonymous
    user must not raise IntegrityError on email_lookup_hash. The
    previous bug: both callers observed an empty users table, both
    tried to INSERT, the second failed with
    `UNIQUE constraint failed: users.email_lookup_hash`.

    The fix is a per-user-id `asyncio.Lock` in `_ensure_db_user` that
    serializes concurrent first-time ensures for the same user_id, so
    the second caller sees the first's committed row in the cache
    instead of racing through the cache miss → INSERT path.
    """
    # _ensure_db_user reads `db.engine.SessionLocal`, so wire it to
    # our test session_factory.
    import db.engine as _engine_mod
    monkeypatch.setattr(_engine_mod, "SessionLocal", session_factory, raising=False)

    from dependencies import _ensure_db_user, _ENSURED_USER_IDS, _ENSURE_LOCKS
    _ENSURED_USER_IDS.clear()
    _ENSURE_LOCKS.clear()

    anon = User(
        user_id="anonymous",
        email="anonymous@localhost",
        name="Anonymous",
        provider="none",
    )

    ids = await asyncio.gather(*[_ensure_db_user(anon) for _ in range(5)])

    # All concurrent callers receive the same DB id…
    assert all(uid == ids[0] for uid in ids), (
        f"expected all callers to observe the same id, got {ids}"
    )
    assert ids[0] is not None, "expected a non-None id (no IntegrityError)"

    # …and exactly one user row exists.
    async with session_factory() as session:
        from db.repositories import UserRepo
        rows = await UserRepo(session).list_all()
    assert len(rows) == 1, f"expected 1 anonymous user row, got {len(rows)}"
