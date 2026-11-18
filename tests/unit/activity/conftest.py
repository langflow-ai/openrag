import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.models import ChatConversation, ChatMessage, User  # noqa: E402


@pytest_asyncio.fixture
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'a.db'}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi, _):
        dbapi.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(factory, *, provenance=True, error=False):
    """Two users, one owned conversation with a user turn and an assistant answer."""
    async with factory() as s:
        for uid in ("alice", "bob"):
            s.add(User(id=uid, oauth_provider="t", oauth_subject=uid))
        s.add(ChatConversation(id="c1", user_id="alice", total_messages=2))
        s.add(ChatConversation(id="c2", user_id="alice", total_messages=1))
        await s.flush()
        s.add(ChatMessage(id="mu", conversation_id="c1", sequence=0, role="user", content="q"))
        s.add(
            ChatMessage(
                id="ma",
                conversation_id="c1",
                sequence=1,
                role="assistant",
                content="a",
                error=error,
                event_data={
                    "provenance": {
                        "model_provider": "openai",
                        "model": "m1",
                        "retrieval": {"document_ids": ["d1"], "chunk_ids": ["k1"]},
                    }
                }
                if provenance
                else {},
            )
        )
        s.add(
            ChatMessage(
                id="mo",
                conversation_id="c2",
                sequence=0,
                role="assistant",
                content="x",
                event_data={"provenance": {"model": "m"}},
            )
        )
        await s.commit()


@pytest.fixture
def seed_data(factory):
    import asyncio

    asyncio.get_event_loop_policy()
    return lambda **kw: seed(factory, **kw)
