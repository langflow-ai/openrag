"""Claim-race recovery must not discard the caller's transaction."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.models import SessionOwnership  # noqa: E402
from db.repositories.session_ownership_repo import SessionOwnershipRepo  # noqa: E402


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "winner_user,winner_canonical,accepted",
    [("alice", "canonical", True), ("bob", "canonical", False), ("alice", "other", False)],
)
async def test_alias_race_preserves_pending_canonical_claim(
    monkeypatch, session_factory, winner_user, winner_canonical, accepted
):
    async with session_factory() as session:
        session.add(
            SessionOwnership(
                response_id="alias", user_id=winner_user, conversation_id=winner_canonical
            )
        )
        await session.commit()

    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        canonical = await repo.claim("canonical", "alice")
        # Keep additional unflushed work pending as begin_nested is entered.
        canonical.last_accessed = canonical.created_at
        original_get = repo.get
        stale_read = False

        async def stale_get(response_id):
            nonlocal stale_read
            if response_id == "alias" and not stale_read:
                stale_read = True
                return None
            return await original_get(response_id)

        monkeypatch.setattr(repo, "get", stale_get)
        if accepted:
            row = await repo.claim("alias", "alice", "canonical")
            assert row.conversation_id == "canonical"
        else:
            with pytest.raises(PermissionError, match="ownership or conversation conflict"):
                await repo.claim("alias", "alice", "canonical")
        assert session.in_transaction()
        assert (await original_get("canonical")).user_id == "alice"
        await session.commit()

    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        assert (await repo.get("canonical")).user_id == "alice"
        winner = await repo.get("alias")
        assert (winner.user_id, winner.conversation_id) == (winner_user, winner_canonical)


@pytest.mark.asyncio
async def test_nonunique_constraint_is_not_recovered_as_matching_winner(
    monkeypatch, session_factory
):
    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        await repo.claim("canonical", "alice")
        await repo.claim("alias", "alice", "canonical")
        await session.execute(
            text(
                "CREATE TRIGGER reject_alias BEFORE INSERT ON session_ownership "
                "WHEN NEW.response_id = 'alias' BEGIN "
                "SELECT RAISE(ABORT, 'unrelated ownership constraint'); END"
            )
        )
        await session.commit()

    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        await repo.claim("prior", "alice")
        original_get = repo.get

        async def stale_get(response_id):
            if response_id == "alias":
                return None
            return await original_get(response_id)

        monkeypatch.setattr(repo, "get", stale_get)
        with pytest.raises(IntegrityError, match="unrelated ownership constraint"):
            await repo.claim("alias", "alice", "canonical")
        assert session.is_active
        await session.commit()

    async with session_factory() as session:
        assert (await SessionOwnershipRepo(session).get("prior")).user_id == "alice"
