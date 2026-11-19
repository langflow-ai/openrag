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


def test_provenance_reads_raw_search_hits_identifiers_only():
    raw = SimpleNamespace(
        tool_name="raw_search",
        content={
            "hits": {
                "hits": [
                    {"_id": "k7", "_source": {"document_id": "d7", "text": "SECRET"}},
                    {"_id": "k8", "_source": {}},
                    {"_source": {"document_id": 5}},  # missing/invalid ids are skipped
                ]
            }
        },
    )
    result = SimpleNamespace(new_messages=lambda: [SimpleNamespace(parts=[raw])])
    out = NativeChatAgent._provenance("openai", "m", result)
    assert out["retrieval"] == {"document_ids": ["d7"], "chunk_ids": ["k7", "k8"]}
    assert "SECRET" not in json.dumps(out)


def test_feedback_service_is_provided_by_dependency_container():
    from dependencies import get_feedback_service

    svc = object()
    assert get_feedback_service({"feedback_service": svc}) is svc
