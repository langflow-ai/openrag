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
async def test_concurrent_signins_same_user_no_integrity_error(session_factory, monkeypatch):
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

    from dependencies import _ENSURE_LOCKS, _ENSURED_USER_IDS, _ensure_db_user

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


@pytest.mark.asyncio
async def test_same_email_different_provider_no_integrity_error(session_factory):
    """Two *different* identities that share an email must not crash on the
    email_lookup_hash UNIQUE constraint.

    Previous bug: after the email collision, the IntegrityError handler
    retried the INSERT with a fresh UUID id but the *same* email, which hit
    the same UNIQUE constraint again and propagated an uncaught
    `sqlite3.IntegrityError: UNIQUE constraint failed: users.email_lookup_hash`.

    The second identity is now persisted without the email so the request
    succeeds; the email stays attached to the first claimant.
    """

    async def signin(provider: str, subject: str) -> str:
        async with session_factory() as session:
            row = await ensure_user_row(
                session,
                User(
                    user_id=subject,
                    email="shared@example.com",
                    name=subject,
                    provider=provider,
                ),
            )
            await session.commit()
            return row.id

    first_id = await signin("google", "g-sub")
    # Same email, different provider/subject — must not raise.
    second_id = await signin("github", "gh-sub")

    assert first_id != second_id

    async with session_factory() as session:
        from db.repositories import UserRepo

        repo = UserRepo(session)
        rows = await repo.list_all()
        # Exactly the email's first claimant keeps the lookup hash.
        with_email = [r for r in rows if r.email_lookup_hash]
    assert len(rows) == 2, f"expected 2 distinct user rows, got {len(rows)}"
    assert len(with_email) == 1, "only the first identity should hold the email"


@pytest.mark.asyncio
async def test_cache_keys_are_per_provider_subject_pair(session_factory, monkeypatch):
    """Two users with the SAME oauth_subject string but DIFFERENT
    providers must NOT share a cache slot. Pre-fix the cache was keyed
    on user.user_id alone, so e.g. AnonymousUser (provider="none",
    user_id="anonymous") would collide with any future identity that
    issued the same subject string.
    """
    import db.engine as _engine_mod

    monkeypatch.setattr(_engine_mod, "SessionLocal", session_factory, raising=False)

    from dependencies import _ENSURE_LOCKS, _ENSURED_USER_IDS, _ensure_db_user

    _ENSURED_USER_IDS.clear()
    _ENSURE_LOCKS.clear()

    # Same subject string, different providers, different emails.
    user_a = User(
        user_id="shared-subject",
        email="a@x.com",
        name="A",
        provider="google",
    )
    user_b = User(
        user_id="shared-subject",
        email="b@x.com",
        name="B",
        provider="ibm",
    )

    id_a = await _ensure_db_user(user_a)
    id_b = await _ensure_db_user(user_b)

    # Distinct cache slots…
    assert "google:shared-subject" in _ENSURED_USER_IDS
    assert "ibm:shared-subject" in _ENSURED_USER_IDS
    # …and distinct DB ids (the (oauth_provider, oauth_subject) UNIQUE
    # constraint isn't violated because the two pairs differ on provider).
    assert id_a is not None and id_b is not None
    assert id_a != id_b, "distinct identities must map to distinct DB ids"

    # And distinct locks were created — same-provider concurrent calls
    # serialize, but cross-provider calls don't block each other.
    assert "google:shared-subject" in _ENSURE_LOCKS
    assert "ibm:shared-subject" in _ENSURE_LOCKS
    assert _ENSURE_LOCKS["google:shared-subject"] is not _ENSURE_LOCKS["ibm:shared-subject"]


@pytest.mark.asyncio
async def test_invalidate_pops_only_target_identity(session_factory, monkeypatch):
    """invalidate_user_ensured_cache(provider, subject) must pop only
    the matching identity's cache + lock entries — not the whole cache."""
    import db.engine as _engine_mod

    monkeypatch.setattr(_engine_mod, "SessionLocal", session_factory, raising=False)

    from dependencies import (
        _ENSURE_LOCKS,
        _ENSURED_USER_IDS,
        _ensure_db_user,
        invalidate_user_ensured_cache,
    )

    _ENSURED_USER_IDS.clear()
    _ENSURE_LOCKS.clear()

    await _ensure_db_user(User(user_id="alice-sub", email="a@x", name="A", provider="google"))
    await _ensure_db_user(User(user_id="bob-sub", email="b@x", name="B", provider="ibm"))
    assert {"google:alice-sub", "ibm:bob-sub"} <= set(_ENSURED_USER_IDS.keys())

    invalidate_user_ensured_cache("google", "alice-sub")

    assert "google:alice-sub" not in _ENSURED_USER_IDS
    assert "google:alice-sub" not in _ENSURE_LOCKS
    # bob's entries untouched
    assert "ibm:bob-sub" in _ENSURED_USER_IDS
    assert "ibm:bob-sub" in _ENSURE_LOCKS

    # Calling with no args clears everything.
    invalidate_user_ensured_cache()
    assert len(_ENSURED_USER_IDS) == 0
    assert len(_ENSURE_LOCKS) == 0
