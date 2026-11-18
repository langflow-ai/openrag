import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from services.native_chat_agent import NativeChatAgent


def test_single_migration_head():
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["0011_message_feedback"]


def test_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url.replace("sqlite:", "sqlite+aiosqlite:"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    insp = sa.inspect(engine)
    assert "message_feedback" in insp.get_table_names()
    names = {i["name"] for i in insp.get_indexes("message_feedback")}
    assert {"ix_message_feedback_created", "ix_message_feedback_rating_created"} <= names
    engine.dispose()
    command.downgrade(cfg, "0010_move_legacy_native_chat")
    engine = sa.create_engine(url)
    assert "message_feedback" not in sa.inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(cfg, "head")


def fake_result(sources):
    part = SimpleNamespace(tool_name="search_documents", content={"results": sources})
    return SimpleNamespace(new_messages=lambda: [SimpleNamespace(parts=[part])])


def test_provenance_distinguishes_empty_retrieval_and_stores_ids_only():
    known = NativeChatAgent._provenance(
        "openai", "m", fake_result([{"document_id": "d", "chunk_id": "k", "text": "SECRET"}])
    )
    assert known["retrieval"] == {"document_ids": ["d"], "chunk_ids": ["k"]}
    assert "SECRET" not in json.dumps(known)
    empty = NativeChatAgent._provenance("openai", "m", fake_result([]))
    assert empty["retrieval"] == {"document_ids": [], "chunk_ids": []}


@pytest.mark.asyncio
async def test_save_completed_turn_returns_none_when_persistence_fails():
    agent = NativeChatAgent()
    agent._save_turn = AsyncMock(side_effect=RuntimeError("db"))
    assert await agent._save_completed_turn("c", "u", "r", [], None) is None
    agent._save_turn = AsyncMock(return_value="mid")
    assert await agent._save_completed_turn("c", "u", "r", [], None) == "mid"
