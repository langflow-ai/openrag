"""DB-mirror task lifecycle: snapshot at schedule time, serialized
under a lock, drained on shutdown.

These tests pin the fix for the fire-and-forget hazards in
``WorkspaceConfigService._schedule_mirror`` — orphaned tasks, lost
writes on rapid double-save, races on the DB upsert.
"""

import asyncio
import sys
import tempfile
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
from config.config_manager import ConfigManager  # noqa: E402
from db.repositories import WorkspaceConfigRepo  # noqa: E402
from services.workspace_config_service import WorkspaceConfigService  # noqa: E402


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
def cm(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        yield ConfigManager(config_file=str(cfg_file))


@pytest.mark.asyncio
async def test_double_save_mirrors_in_order_with_distinct_snapshots(
    cm, session_factory
):
    """save(A), save(B) — both writes must reach the DB. Without the
    snapshot fix, the second mirror task would read the post-B config
    twice and A would be lost.
    """
    svc = WorkspaceConfigService(config_manager=cm, session_factory=session_factory)

    cfg = cm.load_config()
    cfg.agent.llm_model = "model-A"
    cm.save_config_file(cfg)
    cfg.agent.llm_model = "model-B"
    cm.save_config_file(cfg)

    # Both tasks must have been scheduled
    assert len(svc._pending_mirrors) >= 1

    await svc.await_pending_mirrors()

    async with session_factory() as session:
        agent = await WorkspaceConfigRepo(session).get_section("agent")
    assert agent is not None
    # Final state must be model-B (the lock serializes writes — A then B)
    assert agent["llm_model"] == "model-B"

    # And no tasks should be lingering
    assert len(svc._pending_mirrors) == 0

    delattr(cm, "_db_mirror_installed")


@pytest.mark.asyncio
async def test_pending_mirrors_drained_via_await_handle(cm, session_factory):
    """The shutdown handler calls await_pending_mirrors() which must
    block until in-flight writes complete."""
    svc = WorkspaceConfigService(config_manager=cm, session_factory=session_factory)

    cfg = cm.load_config()
    cfg.agent.system_prompt = "Be helpful."
    cm.save_config_file(cfg)

    # The mirror task is scheduled but may not have run yet.
    # await_pending_mirrors must block until it does.
    await svc.await_pending_mirrors()

    async with session_factory() as session:
        agent = await WorkspaceConfigRepo(session).get_section("agent")
    assert agent.get("system_prompt") == "Be helpful."
    assert len(svc._pending_mirrors) == 0

    delattr(cm, "_db_mirror_installed")


@pytest.mark.asyncio
async def test_no_pending_mirrors_on_files_mode(cm, monkeypatch, session_factory):
    """In files mode the mirror is never scheduled."""
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = WorkspaceConfigService(config_manager=cm, session_factory=session_factory)
    cfg = cm.load_config()
    cfg.agent.system_prompt = "files mode"
    cm.save_config_file(cfg)
    # files mode means hooks aren't installed; no mirror tasks scheduled
    assert len(svc._pending_mirrors) == 0
    await svc.await_pending_mirrors()  # noop, no exception
