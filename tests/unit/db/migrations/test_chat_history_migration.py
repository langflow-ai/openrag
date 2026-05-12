"""Runtime migration: session_ownership.json + conversations.json → DB."""

import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import ConversationRepo, SessionOwnershipRepo  # noqa: E402
from db import migrations_runtime  # noqa: E402


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
def staged_files(tmp_path, monkeypatch):
    """Drop sample JSON files where the migration expects them."""
    so_path = tmp_path / "session_ownership.json"
    conv_path = tmp_path / "conversations.json"

    so_path.write_text(json.dumps({
        "sess-1": {
            "user_id": "alice",
            "created_at": "2026-04-01T10:00:00",
            "last_accessed": "2026-04-02T11:00:00",
        },
        "sess-2": {
            "user_id": "bob",
            "created_at": "2026-04-03T09:00:00",
            "last_accessed": "2026-04-03T09:00:00",
        },
    }))

    conv_path.write_text(json.dumps({
        "alice": {
            "r-1": {
                "title": "Project sync",
                "endpoint": "chat",
                "previous_response_id": None,
                "filter_id": None,
                "total_messages": 4,
                "created_at": "2026-04-01T10:00:00",
                "last_activity": "2026-04-02T11:00:00",
            },
        },
        "bob": {
            "r-2": {
                "title": "Bug triage",
                "endpoint": "langflow",
                "total_messages": 1,
                "created_at": "2026-04-03T09:00:00",
                "last_activity": "2026-04-03T09:00:00",
            },
        },
    }))

    def _resolver(name):
        return str(tmp_path / name)

    monkeypatch.setattr(migrations_runtime, "get_data_file", _resolver)
    yield tmp_path


@pytest.mark.asyncio
async def test_migration_copies_both_files(staged_files, session_factory):
    async with session_factory() as session:
        stats = await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()

    assert stats["sessions_inserted"] == 2
    assert stats["conversations_inserted"] == 2

    async with session_factory() as session:
        so_repo = SessionOwnershipRepo(session)
        assert (await so_repo.get("sess-1")).user_id == "alice"
        assert (await so_repo.get("sess-2")).user_id == "bob"

        conv_repo = ConversationRepo(session)
        r1 = await conv_repo.get("r-1")
        assert r1.title == "Project sync"
        assert r1.user_id == "alice"
        assert r1.total_messages == 4
        r2 = await conv_repo.get("r-2")
        assert r2.endpoint == "langflow"


@pytest.mark.asyncio
async def test_migration_is_idempotent(staged_files, session_factory):
    """Re-running yields zero new rows (no upsert overwrite, no errors)."""
    async with session_factory() as session:
        first = await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()

    async with session_factory() as session:
        second = await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()

    assert first["sessions_inserted"] == 2
    assert first["conversations_inserted"] == 2
    # Second pass: rows already there, no new inserts
    assert second["sessions_inserted"] == 0
    assert second["conversations_inserted"] == 0


@pytest.mark.asyncio
async def test_migration_no_files_is_noop(tmp_path, monkeypatch, session_factory):
    """Migration on a fresh install (no JSON files) succeeds silently."""
    monkeypatch.setattr(
        migrations_runtime,
        "get_data_file",
        lambda name: str(tmp_path / name),
    )
    async with session_factory() as session:
        stats = await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()
    assert stats == {"sessions_inserted": 0, "conversations_inserted": 0}


@pytest.mark.asyncio
async def test_run_marks_migration_done(staged_files, session_factory):
    """Top-level run() records the step in migration_status."""
    async with session_factory() as session:
        await migrations_runtime.run(session)
        await session.commit()

    async with session_factory() as session:
        assert await migrations_runtime._already_done(
            session, migrations_runtime.CHAT_HISTORY_JSON_TO_DB_V1
        )
