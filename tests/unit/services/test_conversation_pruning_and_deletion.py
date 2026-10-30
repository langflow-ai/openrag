"""Pruning TTL validation, prune rollback races, and file-save failure handling."""

import asyncio
import errno
import json
import sys
from datetime import UTC, datetime, timedelta
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
from db.repositories import ConversationRepo  # noqa: E402
from services.conversation_persistence_service import (  # noqa: E402
    ConversationPersistenceService,
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
def storage_path(tmp_path):
    return tmp_path / "conversations.json"


def _svc(storage_path, session_factory) -> ConversationPersistenceService:
    return ConversationPersistenceService(
        storage_file=str(storage_path),
        session_factory=session_factory,
    )


def _payload(response_id="r-1", title="Hello", *, age_days=0) -> dict:
    last_activity = datetime.now() - timedelta(days=age_days)
    return {
        "response_id": response_id,
        "title": title,
        "endpoint": "chat",
        "previous_response_id": None,
        "filter_id": None,
        "total_messages": 1,
        "last_activity": last_activity.isoformat(),
    }


async def _seed_db(session_factory, response_id: str, *, user_id="alice", age_days=0) -> None:
    async with session_factory() as session:
        await ConversationRepo(session).upsert(
            response_id=response_id,
            user_id=user_id,
            title="db row",
            last_activity=datetime.now(UTC) - timedelta(days=age_days),
        )
        await session.commit()


async def _db_ids(session_factory) -> set[str]:
    async with session_factory() as session:
        rows = await ConversationRepo(session).list_for_user("alice")
    return {row.response_id for row in rows}


async def _failing_save() -> None:
    raise OSError("disk full")


# ---------------------------------------------------------------------------
# 1. ttl_days must be >= 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_days", [0, -1, -30])
async def test_service_rejects_non_positive_ttl_and_changes_nothing(
    monkeypatch, storage_path, session_factory, ttl_days
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "old", _payload("old", age_days=90))
    await _seed_db(session_factory, "old-db", age_days=90)
    on_disk_before = storage_path.read_text()
    memory_before = json.loads(json.dumps(svc._conversations))

    with pytest.raises(ValueError, match="at least 1"):
        await svc.prune_stale_conversations(ttl_days)

    assert svc._conversations == memory_before
    assert storage_path.read_text() == on_disk_before
    assert "old-db" in await _db_ids(session_factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_days", [0, -1, -30])
async def test_repo_rejects_non_positive_ttl_and_deletes_nothing(session_factory, ttl_days):
    await _seed_db(session_factory, "old-db", age_days=90)

    async with session_factory() as session:
        with pytest.raises(ValueError, match="at least 1"):
            await ConversationRepo(session).delete_stale(ttl_days)

    assert await _db_ids(session_factory) == {"old-db"}


@pytest.mark.asyncio
async def test_positive_ttl_prunes_old_and_keeps_recent(monkeypatch, storage_path, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "old", _payload("old", age_days=90))
    await svc.store_conversation_thread("alice", "recent", _payload("recent", age_days=1))
    await _seed_db(session_factory, "old-db", age_days=90)
    await _seed_db(session_factory, "recent-db", age_days=1)

    deleted = await svc.prune_stale_conversations(30)

    assert deleted >= 2
    assert set(svc._conversations["alice"]) == {"recent"}
    assert set(json.loads(storage_path.read_text())["alice"]) == {"recent"}
    ids = await _db_ids(session_factory)
    assert "old-db" not in ids
    assert "recent-db" in ids


# ---------------------------------------------------------------------------
# 2. Failed-prune rollback must not clobber concurrent updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_prune_rollback_keeps_a_newer_concurrent_version(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    stale = _payload("old", title="stale version", age_days=90)
    svc._conversations = {"alice": {"old": stale}}

    save_started = asyncio.Event()
    release_save = asyncio.Event()
    calls = 0

    async def save():
        nonlocal calls
        calls += 1
        if calls == 1:  # the prune's own save: pause, then fail
            save_started.set()
            await release_save.wait()
            raise OSError("disk full")

    svc._save_conversations = save

    prune = asyncio.create_task(svc.prune_stale_conversations(30))
    await save_started.wait()
    # Pruning has removed the entry and is blocked in its save; a newer
    # version of the same conversation is stored meanwhile.
    assert "old" not in svc._conversations["alice"]
    newer = _payload("old", title="newer version", age_days=0)
    await svc.store_conversation_thread("alice", "old", newer)
    release_save.set()

    assert await prune == 0
    assert svc._conversations["alice"]["old"]["title"] == "newer version"


@pytest.mark.asyncio
async def test_failed_prune_rollback_restores_an_unchanged_entry(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    stale = _payload("old", title="stale version", age_days=90)
    svc._conversations = {"alice": {"old": stale}}
    svc._save_conversations = _failing_save

    assert await svc.prune_stale_conversations(30) == 0

    assert svc._conversations["alice"]["old"] == stale


# ---------------------------------------------------------------------------
# 3. File-save failures must not skip the DB delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_thread_still_deletes_from_db_when_file_save_fails(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    assert "r-1" in await _db_ids(session_factory)
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.delete_conversation_thread("alice", "r-1")

    assert "r-1" not in await _db_ids(session_factory)
    assert "r-1" not in svc._conversations.get("alice", {})


@pytest.mark.asyncio
async def test_clear_user_still_deletes_from_db_when_file_save_fails(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    await svc.store_conversation_thread("alice", "r-2", _payload("r-2"))
    assert await _db_ids(session_factory) == {"r-1", "r-2"}
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.clear_user_conversations("alice")

    assert await _db_ids(session_factory) == set()
    assert "alice" not in svc._conversations


@pytest.mark.asyncio
async def test_files_only_delete_failure_is_logged_not_durable(
    monkeypatch, storage_path, session_factory
):
    """In files mode a failed save leaves the entry on disk.

    The error is raised so the caller knows the delete was not durable: a
    restart before another successful save brings the conversation back. A
    later successful save rewrites the file from memory.
    """
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    await svc.store_conversation_thread("alice", "r-2", _payload("r-2"))
    real_save = svc._save_conversations
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.delete_conversation_thread("alice", "r-1")

    assert "r-1" not in svc._conversations["alice"]
    assert set(json.loads(storage_path.read_text())["alice"]) == {"r-1", "r-2"}
    reloaded = _svc(storage_path, session_factory)
    assert "r-1" in reloaded._conversations["alice"]

    svc._save_conversations = real_save
    await svc._save_conversations()
    assert set(json.loads(storage_path.read_text())["alice"]) == {"r-2"}


@pytest.mark.asyncio
async def test_files_only_clear_failure_is_logged_not_durable(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.clear_user_conversations("alice")

    assert "alice" not in svc._conversations
    assert "r-1" in json.loads(storage_path.read_text())["alice"]


@pytest.mark.asyncio
async def test_files_only_delete_retry_saves_again_after_failed_save(
    monkeypatch, storage_path, session_factory
):
    """A retry must rewrite the file even though memory no longer has the entry."""
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    await svc.store_conversation_thread("alice", "r-2", _payload("r-2"))
    real_save = svc._save_conversations
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.delete_conversation_thread("alice", "r-1")

    svc._save_conversations = real_save
    assert await svc.delete_conversation_thread("alice", "r-1") is True
    assert set(json.loads(storage_path.read_text())["alice"]) == {"r-2"}

    # Once the file reflects the delete, nothing is pending any more.
    assert await svc.delete_conversation_thread("alice", "r-1") is False


@pytest.mark.asyncio
async def test_files_only_clear_retry_saves_again_after_failed_save(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "r-1", _payload("r-1"))
    real_save = svc._save_conversations
    svc._save_conversations = _failing_save

    with pytest.raises(OSError, match="disk full"):
        await svc.clear_user_conversations("alice")

    svc._save_conversations = real_save
    await svc.clear_user_conversations("alice")
    assert "alice" not in json.loads(storage_path.read_text())


# ---------------------------------------------------------------------------
# 4. A failed prune must not resurrect a conversation deleted meanwhile
# ---------------------------------------------------------------------------


async def _pause_then_fail_first_save(svc):
    """Make the prune's save block until released, then fail; later saves succeed."""
    save_started = asyncio.Event()
    release_save = asyncio.Event()
    real_save = svc._save_conversations
    calls = 0

    async def save():
        nonlocal calls
        calls += 1
        if calls == 1:
            save_started.set()
            await release_save.wait()
            raise OSError("disk full")
        await real_save()

    svc._save_conversations = save
    return save_started, release_save


@pytest.mark.asyncio
async def test_failed_prune_does_not_resurrect_an_explicitly_deleted_conversation(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "old", _payload("old", age_days=90))
    save_started, release_save = await _pause_then_fail_first_save(svc)

    prune = asyncio.create_task(svc.prune_stale_conversations(30))
    await save_started.wait()
    # The prune has removed "old" from memory and is stuck in its save. An
    # explicit delete now finds nothing to remove from the file store.
    delete = asyncio.create_task(svc.delete_conversation_thread("alice", "old"))
    await asyncio.sleep(0)  # let the delete run as far as it can
    release_save.set()
    await prune
    assert await delete is True

    assert "old" not in svc._conversations.get("alice", {})
    assert "old" not in await svc.get_user_conversations("alice")
    assert "old" not in await _db_ids(session_factory)


@pytest.mark.asyncio
async def test_failed_prune_does_not_resurrect_a_cleared_user(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "old", _payload("old", age_days=90))
    save_started, release_save = await _pause_then_fail_first_save(svc)

    prune = asyncio.create_task(svc.prune_stale_conversations(30))
    await save_started.wait()
    clear = asyncio.create_task(svc.clear_user_conversations("alice"))
    await asyncio.sleep(0)
    release_save.set()
    await prune
    await clear

    assert not svc._conversations.get("alice")
    assert await svc.get_user_conversations("alice") == {}
    assert await _db_ids(session_factory) == set()


# ---------------------------------------------------------------------------
# 5. Directory fsync after the atomic replace
# ---------------------------------------------------------------------------


def _fail_dir_fsync(monkeypatch, err):
    import services.conversation_persistence_service as mod

    def boom(path):
        raise err

    monkeypatch.setattr(mod.ConversationPersistenceService, "_fsync_dir", staticmethod(boom))


@pytest.mark.parametrize("code", [errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP])
def test_fsync_dir_ignores_unsupported_errors(monkeypatch, tmp_path, code):
    import services.conversation_persistence_service as mod

    def unsupported(fd):
        raise OSError(code, "unsupported")

    monkeypatch.setattr(mod.os, "fsync", unsupported)
    ConversationPersistenceService._fsync_dir(str(tmp_path))  # must not raise


def test_fsync_dir_propagates_real_errors(monkeypatch, tmp_path):
    import services.conversation_persistence_service as mod

    def eio(fd):
        raise OSError(errno.EIO, "io error")

    monkeypatch.setattr(mod.os, "fsync", eio)
    with pytest.raises(OSError):
        ConversationPersistenceService._fsync_dir(str(tmp_path))


@pytest.mark.asyncio
async def test_prune_keeps_memory_matching_replaced_file_when_dir_fsync_fails(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)
    await svc.store_conversation_thread("alice", "old", _payload("old", age_days=90))
    await svc.store_conversation_thread("alice", "recent", _payload("recent"))
    _fail_dir_fsync(monkeypatch, OSError(errno.EIO, "io error"))

    assert await svc.prune_stale_conversations(30) == 1

    assert set(svc._conversations["alice"]) == {"recent"}
    assert set(json.loads(storage_path.read_text())["alice"]) == {"recent"}
