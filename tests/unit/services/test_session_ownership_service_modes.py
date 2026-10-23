"""SessionOwnershipService — hybrid / db / files mode coverage."""

import asyncio
import json
import os
import stat
import sys
import threading
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
    stale_read = False

    async def stale_get(repo, response_id):
        nonlocal stale_read
        if response_id == "contended" and not stale_read:
            stale_read = True
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


@pytest.mark.asyncio
async def test_file_fsync_keeps_event_loop_responsive(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(None)
    heartbeat = threading.Event()
    responsive = []
    original_fsync = os.fsync

    def delayed_fsync(fd):
        responsive.append(heartbeat.wait(timeout=1))
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", delayed_fsync)
    claim = asyncio.create_task(svc.claim_session("alice", "canonical"))
    await asyncio.sleep(0)
    heartbeat.set()
    assert await claim is True
    assert responsive and all(responsive), "fsync blocked the event-loop heartbeat"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["claim", "release", "release_group"])
async def test_concurrent_file_mutations_keep_every_committed_change(
    monkeypatch, tmp_data_dir, mutation
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(None)
    assert await svc.claim_session("alice", "existing") is True
    assert await svc.claim_session("alice", "victim") is True
    entered = threading.Event()
    finish = threading.Event()
    original_fsync = os.fsync

    def pause_first_fsync(fd):
        if not entered.is_set():
            entered.set()
            assert finish.wait(timeout=2), "file persistence blocked the event loop"
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", pause_first_fsync)
    first = asyncio.create_task(svc.claim_session("alice", "first"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if mutation == "claim":
            operation = svc.claim_session("alice", "second")
        elif mutation == "release":
            operation = svc.release_session("alice", "victim")
        else:
            operation = svc.release_conversation_sessions("alice", ["victim"])
        second = asyncio.create_task(operation)
        await asyncio.sleep(0)
    finally:
        finish.set()
    first_result, _ = await asyncio.gather(first, second)
    assert first_result is True
    expected = (
        {"existing", "first", "victim", "second"}
        if mutation == "claim"
        else {
            "existing",
            "first",
        }
    )
    assert set(svc.ownership_data) == expected
    assert set(json.loads(tmp_data_dir.read_text())) == expected
    assert set(await _svc(None).get_user_sessions("alice")) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["claim", "release", "release_group"])
async def test_failed_file_mutation_preserves_durable_ownership(
    monkeypatch, tmp_data_dir, mutation
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(None)
    assert await svc.claim_session("alice", "canonical") is True
    before = tmp_data_dir.read_bytes()

    def fail_replace(*args):
        raise OSError("atomic replacement unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    if mutation == "claim":
        assert await svc.claim_session("alice", "alias", conversation_id="canonical") is False
    else:
        with pytest.raises(OSError, match="atomic replacement unavailable"):
            if mutation == "release":
                await svc.release_session("alice", "canonical")
            else:
                await svc.release_conversation_sessions("alice", ["canonical"])
    assert tmp_data_dir.read_bytes() == before
    assert svc.ownership_data == json.loads(before)
    assert await _svc(None).get_user_sessions("alice") == ["canonical"]
    assert list(tmp_data_dir.parent.iterdir()) == [tmp_data_dir]


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_fails", [False, True])
async def test_file_claim_waits_for_directory_durability_before_publishing(
    monkeypatch, tmp_data_dir, sync_fails
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(None)
    entered = threading.Event()
    finish = threading.Event()
    directory_fds = []
    original_fsync = os.fsync

    def pause_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fds.append(fd)
            entered.set()
            assert finish.wait(timeout=2), "directory sync blocked the event loop"
            if sync_fails:
                raise OSError("directory sync unavailable")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", pause_directory_fsync)
    claim = asyncio.create_task(svc.claim_session("alice", "canonical"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        # Replacement alone is not a durable claim and must not authorize it.
        assert json.loads(tmp_data_dir.read_text())["canonical"]["user_id"] == "alice"
        assert not claim.done()
        assert await svc.get_session_owner("canonical") is None
    finally:
        finish.set()
        result = await claim
    assert result is not sync_fails
    assert await svc.get_session_owner("canonical") == (None if sync_fails else "alice")
    assert len(directory_fds) == 1
    with pytest.raises(OSError):
        os.fstat(directory_fds[0])
    assert list(tmp_data_dir.parent.iterdir()) == [tmp_data_dir]


@pytest.mark.asyncio
async def test_atomic_file_replacement_preserves_existing_permissions(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(None)
    assert await svc.claim_session("alice", "canonical") is True
    tmp_data_dir.chmod(0o640)
    assert await svc.claim_session("alice", "alias", conversation_id="canonical") is True
    assert stat.S_IMODE(tmp_data_dir.stat().st_mode) == 0o640


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid"])
@pytest.mark.parametrize(
    ("winner_user", "winner_canonical", "accepted"),
    [
        ("alice", "canonical", True),
        ("bob", "foreign", False),
        ("alice", "other", False),
    ],
)
async def test_real_database_claim_race_checks_winning_owner_and_conversation(
    monkeypatch, tmp_data_dir, tmp_path, mode, winner_user, winner_canonical, accepted
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ownership-race.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    setup = _svc(factory)
    for user, canonical in (("alice", "canonical"), ("alice", "other"), ("bob", "foreign")):
        assert await setup.claim_session(user, canonical) is True
    selected_missing = asyncio.Event()
    winner_committed = asyncio.Event()
    original_get = SessionOwnershipRepo.get

    async def pause_after_missing_read(repo, response_id):
        row = await original_get(repo, response_id)
        if response_id == "contended" and row is None and not selected_missing.is_set():
            selected_missing.set()
            await winner_committed.wait()
        return row

    monkeypatch.setattr(SessionOwnershipRepo, "get", pause_after_missing_read)
    loser = _svc(factory)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    pending = asyncio.create_task(
        loser.claim_session("alice", "contended", conversation_id="canonical")
    )
    try:
        await asyncio.wait_for(selected_missing.wait(), timeout=2)
        # The loser already read no row; this insert commits on another real
        # connection before its stale INSERT hits the primary-key constraint.
        monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
        assert (
            await _svc(factory).claim_session(
                winner_user, "contended", conversation_id=winner_canonical
            )
            is True
        )
        monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    finally:
        winner_committed.set()
    try:
        assert await pending is accepted
        fresh = _svc(factory)
        assert await fresh.get_session_owner("contended") == winner_user
        if accepted:
            assert set(await fresh.get_conversation_sessions("alice", "canonical")) == {
                "canonical",
                "contended",
            }
        else:
            assert "contended" not in loser.ownership_data
        if mode == "hybrid":
            assert tmp_data_dir.exists() is accepted
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid"])
async def test_unrelated_database_integrity_error_is_not_an_owned_race(
    monkeypatch, tmp_data_dir, session_factory, mode
):
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    assert await _svc(session_factory).claim_session("alice", "canonical") is True
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    svc = _svc(session_factory)

    async def unrelated_failure(*args):
        raise IntegrityError("UPDATE session_ownership", {}, ValueError("unrelated constraint"))

    monkeypatch.setattr(SessionOwnershipRepo, "claim", unrelated_failure)
    with pytest.raises(IntegrityError, match="unrelated constraint"):
        await svc.claim_session("alice", "canonical")
    assert svc.ownership_data == {}
    assert not tmp_data_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid"])
async def test_nonunique_insert_integrity_error_cannot_reuse_compatible_owner(
    monkeypatch, tmp_data_dir, session_factory, mode
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    assert await _svc(session_factory).claim_session("alice", "canonical") is True
    async with session_factory() as session:
        await session.execute(
            text(
                "CREATE TRIGGER reject_ownership_insert BEFORE INSERT ON session_ownership "
                "BEGIN SELECT RAISE(ABORT, 'unrelated ownership constraint'); END"
            )
        )
        await session.commit()
    original_get = SessionOwnershipRepo.get
    stale_read = False

    async def stale_once(repo, response_id):
        nonlocal stale_read
        if response_id == "canonical" and not stale_read:
            stale_read = True
            return None
        return await original_get(repo, response_id)

    monkeypatch.setattr(SessionOwnershipRepo, "get", stale_once)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    svc = _svc(session_factory)
    with pytest.raises(IntegrityError, match="unrelated ownership constraint"):
        await svc.claim_session("alice", "canonical")
    assert svc.ownership_data == {}
    assert not tmp_data_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["db", "hybrid", "files"])
async def test_legacy_null_association_remains_its_own_canonical_conversation(
    monkeypatch, tmp_data_dir, session_factory, mode
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", mode)
    svc = _svc(session_factory)
    assert await svc.claim_session("alice", "legacy") is True
    assert await svc.claim_session("alice", "other") is True
    if mode != "files":
        async with session_factory() as session:
            row = await SessionOwnershipRepo(session).get("legacy")
            row.conversation_id = None
            await session.commit()
    if mode != "db":
        data = json.loads(tmp_data_dir.read_text())
        data["legacy"]["conversation_id"] = None
        tmp_data_dir.write_text(json.dumps(data))
    fresh = _svc(session_factory)
    assert await fresh.claim_session("alice", "legacy", conversation_id="other") is False
    assert await fresh.get_conversation_sessions("alice", "legacy") == ["legacy"]
