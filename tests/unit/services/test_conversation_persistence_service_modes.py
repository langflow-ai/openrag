"""ConversationPersistenceService — hybrid / db / files mode coverage."""

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


def _payload(title="Hello", endpoint="chat") -> dict:
    return {
        "response_id": "r-1",
        "title": title,
        "endpoint": endpoint,
        "previous_response_id": None,
        "filter_id": None,
        "total_messages": 3,
    }


@pytest.mark.asyncio
async def test_db_mode_writes_to_db_only(monkeypatch, storage_path, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(storage_path, session_factory)

    await svc.store_conversation_thread("alice", "r-1", _payload())

    # JSON never created
    assert not storage_path.exists()

    # DB row present
    async with session_factory() as session:
        row = await ConversationRepo(session).get("r-1")
        assert row is not None
        assert row.user_id == "alice"
        assert row.title == "Hello"
        assert row.total_messages == 3


@pytest.mark.asyncio
async def test_files_mode_writes_to_json_only(monkeypatch, storage_path, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = _svc(storage_path, session_factory)

    await svc.store_conversation_thread("alice", "r-1", _payload())

    assert storage_path.exists()
    body = json.loads(storage_path.read_text())
    assert body["alice"]["r-1"]["title"] == "Hello"

    async with session_factory() as session:
        row = await ConversationRepo(session).get("r-1")
        assert row is None


@pytest.mark.asyncio
async def test_hybrid_mode_dual_writes(monkeypatch, storage_path, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = _svc(storage_path, session_factory)

    await svc.store_conversation_thread("alice", "r-1", _payload())

    assert storage_path.exists()
    async with session_factory() as session:
        assert await ConversationRepo(session).get("r-1") is not None


@pytest.mark.asyncio
async def test_db_mode_ignores_pre_existing_json(
    monkeypatch, storage_path, session_factory
):
    storage_path.write_text(json.dumps({
        "alice": {
            "ghost-r": {"title": "leak", "total_messages": 1}
        }
    }))

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(storage_path, session_factory)

    convs = await svc.get_user_conversations("alice")
    assert convs == {}  # JSON ignored


@pytest.mark.asyncio
async def test_hybrid_merges_db_and_json_on_read(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")

    # Seed JSON with one entry
    storage_path.write_text(json.dumps({
        "alice": {"r-json": {"title": "from-json", "total_messages": 0}}
    }))

    svc = _svc(storage_path, session_factory)
    # Add a DB-only entry
    await svc._db_upsert("alice", "r-db", _payload(title="from-db"))

    convs = await svc.get_user_conversations("alice")
    assert "r-db" in convs and convs["r-db"]["title"] == "from-db"
    assert "r-json" in convs and convs["r-json"]["title"] == "from-json"


@pytest.mark.asyncio
async def test_delete_only_owner_can_delete(monkeypatch, storage_path, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(storage_path, session_factory)

    await svc.store_conversation_thread("alice", "r-1", _payload())
    # Mallory cannot delete
    assert await svc.delete_conversation_thread("mallory", "r-1") is False
    # Alice can
    assert await svc.delete_conversation_thread("alice", "r-1") is True
    async with session_factory() as session:
        assert await ConversationRepo(session).get("r-1") is None


@pytest.mark.asyncio
async def test_clear_user_removes_all_their_threads(
    monkeypatch, storage_path, session_factory
):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = _svc(storage_path, session_factory)

    p1 = _payload()
    p2 = dict(_payload(), response_id="r-2")
    await svc.store_conversation_thread("alice", "r-1", p1)
    await svc.store_conversation_thread("alice", "r-2", p2)
    await svc.store_conversation_thread("bob", "r-3", p1)

    await svc.clear_user_conversations("alice")

    convs = await svc.get_user_conversations("alice")
    assert convs == {}
    bob_convs = await svc.get_user_conversations("bob")
    assert "r-3" in bob_convs
