"""Runtime migration: session_ownership.json + conversations.json → DB."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.migrations_runtime as migrations_runtime  # noqa: E402
import db.models  # noqa: E402,F401
from db.repositories import ChatHistoryRepo, ConversationRepo, SessionOwnershipRepo  # noqa: E402
from services.native_chat_history_service import NativeChatHistoryService  # noqa: E402


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

    so_path.write_text(
        json.dumps(
            {
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
            }
        )
    )

    conv_path.write_text(
        json.dumps(
            {
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
            }
        )
    )

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
    assert stats["conversations_inserted"] == 1
    assert stats["native_conversations"] == 1

    async with session_factory() as session:
        so_repo = SessionOwnershipRepo(session)
        assert (await so_repo.get("sess-1")).user_id == "alice"
        assert (await so_repo.get("sess-2")).user_id == "bob"

        native_repo = ChatHistoryRepo(session)
        r1 = await native_repo.get_conversation("r-1")
        assert r1.title == "Project sync"
        assert r1.user_id == "alice"
        assert r1.total_messages == 4

        conv_repo = ConversationRepo(session)
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
    assert first["conversations_inserted"] == 1
    assert first["native_conversations"] == 1
    # Second pass: rows already there, no new inserts
    assert second["sessions_inserted"] == 0
    assert second["conversations_inserted"] == 0
    assert second["native_conversations"] == 0


@pytest.mark.asyncio
async def test_native_metadata_migration_recovers_messages_and_keeps_empty_history_continuable(
    staged_files, session_factory
):
    """Native metadata-only rows remain valid continuations after migration."""
    conversations = json.loads((staged_files / "conversations.json").read_text())
    conversations["alice"]["r-1"]["messages"] = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": ["user"], "content": "Skip malformed role"},
    ]
    conversations["alice"]["metadata-only"] = {
        "title": "No message snapshot",
        "endpoint": "chat",
        "total_messages": 2,
    }
    (staged_files / "conversations.json").write_text(json.dumps(conversations))

    async with session_factory() as session:
        await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()

    async with session_factory() as session:
        repo = ChatHistoryRepo(session)
        recovered = await repo.list_messages("r-1")
        metadata_only = await repo.get_conversation("metadata-only")

    assert [(row.role, row.content) for row in recovered] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
    ]
    history = await NativeChatHistoryService(session_factory=session_factory).pydantic_history(
        "r-1", "alice"
    )
    assert [part.content for message in history for part in message.parts] == [
        "Earlier question",
        "Earlier answer",
    ]
    assert metadata_only is not None
    assert metadata_only.total_messages == 2


@pytest.mark.asyncio
async def test_native_chat_migration_runs_independently_of_legacy_marker(
    staged_files, session_factory
):
    """Old installations can import native chat after their broad marker is done."""
    async with session_factory() as session:
        assert await migrations_runtime.migrate_legacy_native_chat_history_json_to_db(session) == 1
        assert await migrations_runtime.migrate_legacy_native_chat_history_json_to_db(session) == 0
        assert await ChatHistoryRepo(session).get_conversation("r-1") is not None


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
    assert stats == {
        "sessions_inserted": 0,
        "conversations_inserted": 0,
        "native_conversations": 0,
    }


@pytest.mark.asyncio
async def test_run_marks_migration_done(staged_files, session_factory, monkeypatch):
    """Top-level run() records each completed history migration."""

    async def _no_native_history(_session):
        return 0

    async def _no_langflow_history(_session):
        return {"conversations": 0, "messages": 0, "failed": 0}

    monkeypatch.setattr(
        migrations_runtime, "migrate_legacy_native_chat_history_json_to_db", _no_native_history
    )
    monkeypatch.setattr(
        migrations_runtime, "migrate_langflow_history_to_native", _no_langflow_history
    )
    async with session_factory() as session:
        await migrations_runtime.run(session)
        await session.commit()

    async with session_factory() as session:
        assert await migrations_runtime._already_done(
            session, migrations_runtime.CHAT_HISTORY_JSON_TO_DB_V1
        )
        assert await migrations_runtime._already_done(
            session, migrations_runtime.NATIVE_CHAT_HISTORY_JSON_TO_DB_V1
        )
        assert await migrations_runtime._already_done(
            session, migrations_runtime.LANGFLOW_HISTORY_TO_NATIVE_V1
        )


@pytest.mark.asyncio
async def test_langflow_history_migration_copies_remote_messages(session_factory):
    async with session_factory() as session:
        await ConversationRepo(session).upsert(
            response_id="langflow-1",
            user_id="alice",
            title="Imported thread",
            endpoint="langflow",
            filter_id="filter-1",
            total_messages=5,
        )
        await session.commit()

    async def _fetch_messages(session_id):
        assert session_id == "langflow-1"
        return [
            {"role": "user", "content": "Earlier question", "timestamp": "2026-01-01T10:00:00Z"},
            {
                "role": "assistant",
                "content": "Earlier answer",
                "timestamp": "2026-01-01T10:00:01Z",
                "chunks": [{"type": "response.completed"}],
            },
        ]

    async with session_factory() as session:
        stats = await migrations_runtime.migrate_langflow_history_to_native(
            session, _fetch_messages
        )
        await session.commit()

    assert stats == {"conversations": 1, "messages": 2, "failed": 0}
    async with session_factory() as session:
        conversation = await ChatHistoryRepo(session).get_conversation("langflow-1")
        messages = await ChatHistoryRepo(session).list_messages("langflow-1")
        ownership = await SessionOwnershipRepo(session).get("langflow-1")

    assert conversation.title == "Imported thread"
    assert conversation.filter_id == "filter-1"
    assert conversation.total_messages == 5
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
    ]
    assert messages[1].event_data["chunks"] == [{"type": "response.completed"}]
    assert ownership.user_id == "alice"


@pytest.mark.asyncio
async def test_langflow_history_migration_leaves_failed_sessions_retryable(session_factory):
    async with session_factory() as session:
        await ConversationRepo(session).upsert(
            response_id="unavailable",
            user_id="alice",
            endpoint="langflow",
        )
        await session.commit()

    async def _unavailable(_session_id):
        raise RuntimeError("Langflow is unavailable")

    async with session_factory() as session:
        stats = await migrations_runtime.migrate_langflow_history_to_native(session, _unavailable)
        await session.commit()

    assert stats == {"conversations": 0, "messages": 0, "failed": 1}
    async with session_factory() as session:
        assert await ChatHistoryRepo(session).get_conversation("unavailable") is None


@pytest.mark.asyncio
async def test_json_migration_preserves_alias_association(staged_files, session_factory):
    ownership_file = staged_files / "session_ownership.json"
    payload = json.loads(ownership_file.read_text())
    payload["alias"] = {"user_id": "alice", "conversation_id": "sess-1"}
    ownership_file.write_text(json.dumps(payload))
    async with session_factory() as session:
        await migrations_runtime.migrate_chat_history_json_to_db(session)
        await session.commit()
    async with session_factory() as session:
        repo = SessionOwnershipRepo(session)
        assert (await repo.get("alias")).conversation_id == "sess-1"
        assert set(await repo.list_for_conversation("sess-1", "alice")) == {"sess-1", "alias"}


def test_session_alias_schema_upgrade_and_downgrade():
    migration_path = ROOT / "alembic" / "versions" / "0008_session_conversation_id.py"
    spec = importlib.util.spec_from_file_location("migration_0008", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE session_ownership (response_id VARCHAR(64) PRIMARY KEY, "
                "user_id VARCHAR(64) NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO session_ownership VALUES ('legacy', 'alice')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert (
            connection.execute(
                sa.text(
                    "SELECT conversation_id FROM session_ownership WHERE response_id = 'legacy'"
                )
            ).scalar_one()
            == "legacy"
        )
        assert "ix_session_ownership_conversation_id" in {
            index["name"] for index in sa.inspect(connection).get_indexes("session_ownership")
        }
        migration.downgrade()
        assert (
            connection.execute(
                sa.text("SELECT user_id FROM session_ownership WHERE response_id = 'legacy'")
            ).scalar_one()
            == "alice"
        )
        assert "conversation_id" not in {
            column["name"] for column in sa.inspect(connection).get_columns("session_ownership")
        }
    engine.dispose()


def test_legacy_native_chat_rows_move_out_of_langflow_history():
    migration_path = ROOT / "alembic" / "versions" / "0010_move_legacy_native_chat.py"
    spec = importlib.util.spec_from_file_location("migration_0010", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE langflow_conversations (
                    response_id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    title VARCHAR(512),
                    endpoint VARCHAR(64),
                    previous_response_id VARCHAR(64),
                    filter_id VARCHAR(128),
                    total_messages INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    last_activity DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE chat_messages (
                    id VARCHAR(64) PRIMARY KEY,
                    conversation_id VARCHAR(64) NOT NULL,
                    sequence INTEGER NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    content TEXT,
                    tool_call_id VARCHAR(128),
                    tool_name VARCHAR(128),
                    tool_arguments JSON,
                    tool_result JSON,
                    event_data JSON,
                    error BOOLEAN NOT NULL,
                    interrupted BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_chat_messages_conversation_sequence
                        UNIQUE (conversation_id, sequence),
                    FOREIGN KEY(conversation_id) REFERENCES chat_conversations (id)
                )
                """
            )
        )
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        connection.execute(
            sa.text(
                """
                CREATE TABLE chat_conversations (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    title VARCHAR(512),
                    filter_id VARCHAR(128),
                    total_messages INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    last_activity DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO langflow_conversations VALUES
                    ('legacy-chat', 'alice', 'Native chat', 'chat', NULL, NULL, 2,
                     '2026-04-01', '2026-04-02'),
                    ('langflow-chat', 'alice', 'Flow chat', 'langflow', NULL, NULL, 1,
                     '2026-04-03', '2026-04-04')
                """
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        assert (
            connection.execute(
                sa.text("SELECT title FROM chat_conversations WHERE id = 'legacy-chat'")
            ).scalar_one()
            == "Native chat"
        )
        assert connection.execute(
            sa.text("SELECT response_id FROM langflow_conversations ORDER BY response_id")
        ).scalars().all() == ["langflow-chat"]
        connection.execute(
            sa.text(
                """
                INSERT INTO chat_messages
                    (id, conversation_id, sequence, role, error, interrupted, created_at)
                VALUES ('legacy-chat:0', 'legacy-chat', 0, 'user', 0, 0, '2026-04-01')
                """
            )
        )

        migration.downgrade()
        assert (
            connection.execute(
                sa.text(
                    "SELECT endpoint FROM langflow_conversations WHERE response_id = 'legacy-chat'"
                )
            ).scalar_one()
            == "chat"
        )
        assert connection.execute(sa.text("SELECT COUNT(*) FROM chat_messages")).scalar_one() == 1
    engine.dispose()
