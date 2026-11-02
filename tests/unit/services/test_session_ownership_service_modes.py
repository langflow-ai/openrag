"""SessionOwnershipService — hybrid / db / files mode coverage."""

import json
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
from db.repositories import SessionOwnershipRepo  # noqa: E402
from services.session_ownership_service import (  # noqa: E402
    SessionOwnershipService,
)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect the service's JSON file into a tmp dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    json_path = data_dir / "session_ownership.json"
    # The service resolves the path via get_data_file at construction —
    # patch it to return our tmp path.
    monkeypatch.setattr(
        "services.session_ownership_service.get_data_file",
        lambda name: str(data_dir / name),
    )
    yield json_path


def _svc(session_factory) -> SessionOwnershipService:
    return SessionOwnershipService(session_factory=session_factory)


@pytest.mark.asyncio
async def test_db_mode_writes_to_db_only(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    # JSON never created
    assert not tmp_data_dir.exists()

    # DB has the row
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is not None
        assert row.user_id == "user-a"


@pytest.mark.asyncio
async def test_files_mode_writes_to_json_only(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    # JSON file created
    assert tmp_data_dir.exists()
    payload = json.loads(tmp_data_dir.read_text())
    assert payload["sess-1"]["user_id"] == "user-a"

    # DB untouched
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is None


@pytest.mark.asyncio
async def test_hybrid_mode_writes_both(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(session_factory)

    await svc.claim_session("user-a", "sess-1")

    assert tmp_data_dir.exists()
    async with session_factory() as session:
        row = await SessionOwnershipRepo(session).get("sess-1")
        assert row is not None


@pytest.mark.asyncio
async def test_db_mode_ignores_pre_existing_json(monkeypatch, tmp_data_dir, session_factory):
    """Stale JSON on disk must not bleed through in db mode."""
    tmp_data_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_data_dir.write_text(
        json.dumps(
            {"ghost-sess": {"user_id": "ghost-user", "created_at": "x", "last_accessed": "x"}}
        )
    )

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    owner = await svc.get_session_owner("ghost-sess")
    assert owner is None  # JSON ignored


@pytest.mark.asyncio
async def test_cross_user_ownership_check(monkeypatch, tmp_data_dir, session_factory):
    """User B must not see User A's sessions in any mode."""
    for mode in ("db", "files", "hybrid"):
        monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
        # Fresh service per mode so the in-memory dict and JSON are reset
        if tmp_data_dir.exists():
            tmp_data_dir.unlink()
        svc = _svc(session_factory)

        await svc.claim_session("alice", f"sess-{mode}")
        assert await svc.is_session_owned_by_user(f"sess-{mode}", "alice") is True
        assert await svc.is_session_owned_by_user(f"sess-{mode}", "bob") is False


@pytest.mark.asyncio
async def test_release_only_owner_can_release(monkeypatch, tmp_data_dir, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)

    await svc.claim_session("alice", "sess-1")
    # Mallory tries to steal
    released = await svc.release_session("mallory", "sess-1")
    assert released is False

    # Alice can release
    released = await svc.release_session("alice", "sess-1")
    assert released is True
    assert await svc.get_session_owner("sess-1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid", "files"])
async def test_claim_rejects_owner_and_alias_reassignment(
    monkeypatch, tmp_data_dir, session_factory, mode
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    svc = _svc(session_factory)
    assert await svc.claim_session("alice", "canonical") is True
    assert await svc.claim_session("alice", "other") is True
    assert await svc.claim_session("alice", "alias", conversation_id="canonical") is True
    assert await svc.claim_session("mallory", "alias", conversation_id="other") is False
    assert await svc.claim_session("alice", "alias", conversation_id="other") is False
    assert await svc.claim_session("mallory", "foreign", conversation_id="canonical") is False
    fresh = _svc(session_factory)
    assert await fresh.get_session_owner("alias") == "alice"
    assert await fresh.get_session_owner("foreign") is None
    assert set(await fresh.get_conversation_sessions("alice", "canonical")) == {
        "canonical",
        "alias",
    }
    assert await fresh.get_conversation_sessions("mallory", "canonical") == []


@pytest.mark.asyncio
async def test_hybrid_committed_db_claim_survives_file_failure(
    monkeypatch, tmp_data_dir, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(session_factory)
    tmp_data_dir.mkdir()
    assert await svc.claim_session("alice", "canonical") is True
    assert await svc.claim_session("alice", "alias", conversation_id="canonical") is True
    assert svc.ownership_data == {}
    fresh = _svc(session_factory)
    assert await fresh.get_session_owner("alias") == "alice"
    assert set(await fresh.get_conversation_sessions("alice", "canonical")) == {
        "canonical",
        "alias",
    }


@pytest.mark.asyncio
async def test_hybrid_file_fallback_survives_failed_db_commit(
    monkeypatch, tmp_data_dir, session_factory
):
    from contextlib import asynccontextmanager

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")

    @asynccontextmanager
    async def broken_database():
        async with session_factory() as session:

            async def fail_commit():
                raise OSError("commit unavailable")

            monkeypatch.setattr(session, "commit", fail_commit)
            yield session

    svc = _svc(broken_database)
    assert await svc.claim_session("alice", "canonical") is True
    assert await svc.claim_session("alice", "alias", conversation_id="canonical") is True
    fresh = _svc(session_factory)
    assert await fresh.get_session_owner("alias") == "alice"
    assert set(await fresh.get_conversation_sessions("alice", "canonical")) == {
        "canonical",
        "alias",
    }
    async with session_factory() as session:
        assert await SessionOwnershipRepo(session).get("alias") is None


@pytest.mark.asyncio
async def test_hybrid_database_conflict_cannot_fall_back_to_stale_file(
    monkeypatch, tmp_data_dir, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    assert await _svc(session_factory).claim_session("mallory", "session") is True
    tmp_data_dir.write_text(json.dumps({"session": {"user_id": "alice"}}))
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(session_factory)
    assert await svc.claim_session("alice", "session") is False
    assert await svc.get_session_owner("session") == "mallory"


@pytest.mark.asyncio
async def test_hybrid_db_recovery_backfills_json_only_canonical(
    monkeypatch, tmp_data_dir, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")

    def unavailable_database():
        raise OSError("database unavailable")

    svc = _svc(unavailable_database)
    assert await svc.claim_session("alice", "canonical") is True
    svc._session_factory = session_factory
    assert await svc.claim_session("alice", "alias", conversation_id="canonical") is True
    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        assert (await repo.get("canonical")).user_id == "alice"
        assert (await repo.get("alias")).conversation_id == "canonical"


@pytest.mark.asyncio
async def test_hybrid_deletion_group_ignores_foreign_or_reassigned_db_aliases(
    monkeypatch, tmp_data_dir, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(session_factory)
    assert await svc.claim_session("alice", "canonical") is True
    assert await svc.claim_session("mallory", "foreign") is True
    assert await svc.claim_session("alice", "other") is True
    assert await svc.claim_session("alice", "moved", conversation_id="other") is True
    tmp_data_dir.write_text(
        json.dumps(
            {
                "canonical": {"user_id": "alice", "conversation_id": "canonical"},
                "foreign": {"user_id": "alice", "conversation_id": "canonical"},
                "moved": {"user_id": "alice", "conversation_id": "canonical"},
            }
        )
    )
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    fresh = _svc(session_factory)
    assert await fresh.get_conversation_sessions("alice", "canonical") == ["canonical"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid"])
async def test_failed_group_revocation_preserves_all_ids_for_retry(
    monkeypatch, tmp_data_dir, session_factory, mode
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    svc = _svc(session_factory)
    for response_id in ("canonical", "alias-1", "alias-2"):
        assert await svc.claim_session("alice", response_id, conversation_id="canonical") is True
    original = SessionOwnershipRepo.release

    async def fail_partway(repo, response_id, user_id):
        if response_id == "alias-1":
            raise OSError("revocation unavailable")
        return await original(repo, response_id, user_id)

    monkeypatch.setattr(SessionOwnershipRepo, "release", fail_partway)
    with pytest.raises(OSError, match="revocation unavailable"):
        await svc.release_conversation_sessions("alice", ["alias-2", "alias-1", "canonical"])
    fresh = _svc(session_factory)
    sessions = await fresh.get_conversation_sessions("alice", "canonical")
    assert set(sessions) == {"canonical", "alias-1", "alias-2"}
    monkeypatch.setattr(SessionOwnershipRepo, "release", original)
    await fresh.release_conversation_sessions("alice", sessions)
    assert await _svc(session_factory).get_user_sessions("alice") == []


@pytest.mark.asyncio
async def test_hybrid_losing_db_insert_cannot_publish_fallback_owner(
    monkeypatch, tmp_data_dir, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    winner = _svc(session_factory)
    assert await winner.claim_session("alice", "contended") is True
    # Model a competing claimant whose SELECT happened just before the winner's
    # insert. The ensuing flush hits the real DB primary-key constraint.
    original = SessionOwnershipRepo.get

    async def stale_get(repo, response_id):
        if response_id == "contended":
            return None
        return await original(repo, response_id)

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    loser = _svc(session_factory)
    monkeypatch.setattr(SessionOwnershipRepo, "get", stale_get)
    assert await loser.claim_session("bob", "contended") is False
    assert loser.ownership_data == {}
    assert not tmp_data_dir.exists()
    monkeypatch.setattr(SessionOwnershipRepo, "get", original)
    assert await _svc(session_factory).get_session_owner("contended") == "alice"


@pytest.mark.asyncio
async def test_hybrid_rechecks_cache_after_awaiting_database(
    monkeypatch, tmp_data_dir, session_factory
):
    import asyncio

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(session_factory)
    waiting = asyncio.Event()
    winner_published = asyncio.Event()
    original = svc._db_claim

    async def delayed_claim(user_id, session_id, conversation_id):
        if user_id == "bob":
            waiting.set()
            await winner_published.wait()
            return False
        return await original(user_id, session_id, conversation_id)

    monkeypatch.setattr(svc, "_db_claim", delayed_claim)
    losing_claim = asyncio.create_task(svc.claim_session("bob", "contended"))
    await waiting.wait()
    assert await svc.claim_session("alice", "contended") is True
    winner_published.set()
    assert await losing_claim is False
    assert json.loads(tmp_data_dir.read_text())["contended"]["user_id"] == "alice"
