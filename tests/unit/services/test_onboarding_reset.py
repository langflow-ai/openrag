"""Tests for onboarding reset."""

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
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from services.onboarding_reset import reset_onboarding_in_db  # noqa: E402


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_reset_onboarding_clears_edited_and_step(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    repo = WorkspaceConfigRepo(session)
    await repo.upsert("meta", {"edited": True})
    await repo.upsert(
        "onboarding",
        {"current_step": 4, "selected_nudge": "docs", "openrag_docs_filter_id": "kf-1"},
    )
    await repo.upsert("agent", {"llm_model": "gpt-4o", "llm_provider": "openai"})
    await session.commit()

    result = await reset_onboarding_in_db(session)
    await session.commit()

    meta = await repo.get_section("meta")
    onboarding = await repo.get_section("onboarding")
    agent = await repo.get_section("agent")

    assert result.previous_edited is True
    assert result.previous_step == 4
    assert meta["edited"] is False
    assert onboarding["current_step"] == 0
    assert onboarding.get("selected_nudge") is None
    assert onboarding.get("openrag_docs_filter_id") is None
    assert agent["llm_model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_reset_models_clears_llm_and_embedding(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    repo = WorkspaceConfigRepo(session)
    await repo.upsert("meta", {"edited": True})
    await repo.upsert("onboarding", {"current_step": 4})
    await repo.upsert("agent", {"llm_model": "gpt-4o", "llm_provider": "anthropic"})
    await repo.upsert(
        "knowledge",
        {"embedding_model": "text-embedding-3-small", "embedding_provider": "anthropic"},
    )
    await session.commit()

    await reset_onboarding_in_db(session, reset_models=True)
    await session.commit()

    agent = await repo.get_section("agent")
    knowledge = await repo.get_section("knowledge")

    assert agent["llm_model"] == ""
    assert agent["llm_provider"] == "openai"
    assert knowledge["embedding_model"] == ""
    assert knowledge["embedding_provider"] == "openai"


@pytest.mark.asyncio
async def test_dry_run_does_not_write(session, monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    repo = WorkspaceConfigRepo(session)
    await repo.upsert("meta", {"edited": True})
    await repo.upsert("onboarding", {"current_step": 2})
    await session.commit()

    await reset_onboarding_in_db(session, dry_run=True)

    meta = await repo.get_section("meta")
    onboarding = await repo.get_section("onboarding")
    assert meta["edited"] is True
    assert onboarding["current_step"] == 2
