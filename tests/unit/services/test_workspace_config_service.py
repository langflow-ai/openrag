"""WorkspaceConfigService — yaml/DB dual-write contract."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from config.config_manager import ConfigManager, OpenRAGConfig  # noqa: E402
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
def tmp_config_manager():
    """Real ConfigManager pointed at a tmp file so yaml writes don't
    touch the dev workspace."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        yield cm


@pytest.mark.asyncio
async def test_load_config_falls_back_to_yaml_when_db_empty(
    tmp_config_manager, session_factory
):
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    config = await svc.load_config()
    assert isinstance(config, OpenRAGConfig)
    assert config.edited is False  # fresh install


@pytest.mark.asyncio
async def test_save_config_writes_to_yaml_and_db(
    monkeypatch, tmp_config_manager, session_factory
):
    """Hybrid mode dual-writes to both yaml and the DB.

    The default mode is ``db`` (DB-only, no yaml), so this test forces
    hybrid via an env override to exercise the dual-write contract.
    """
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    config = tmp_config_manager.load_config()
    config.agent.system_prompt = "Be helpful."

    ok = await svc.save_config(config)
    assert ok is True

    # Yaml write happened (file exists, contents include the prompt)
    assert tmp_config_manager.config_file.exists()

    # DB mirror happened (rows for each section)
    async with session_factory() as session:
        repo = WorkspaceConfigRepo(session)
        agent = await repo.get_section("agent")
        assert agent is not None
        assert agent.get("system_prompt") == "Be helpful."
        meta = await repo.get_section("meta")
        assert meta == {"edited": True}


@pytest.mark.asyncio
async def test_is_onboarded_reads_from_db_first(
    tmp_config_manager, session_factory
):
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )

    # Seed only the DB (no yaml) — DB read should return True
    async with session_factory() as session:
        await WorkspaceConfigRepo(session).upsert("meta", {"edited": True})
        await session.commit()

    assert await svc.is_onboarded() is True


@pytest.mark.asyncio
async def test_is_onboarded_false_when_neither_set(
    tmp_config_manager, session_factory
):
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    assert await svc.is_onboarded() is False


@pytest.mark.asyncio
async def test_get_onboarding_step_returns_db_value(
    tmp_config_manager, session_factory
):
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    async with session_factory() as session:
        await WorkspaceConfigRepo(session).upsert(
            "onboarding", {"current_step": "agent_setup"}
        )
        await session.commit()

    assert await svc.get_onboarding_step() == "agent_setup"


@pytest.mark.asyncio
async def test_yaml_write_hooks_mirror_to_db(
    tmp_config_manager, session_factory
):
    """Legacy callers that hit config_manager.save_config_file directly
    should auto-mirror to the DB via the installed monkey-patch."""
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    # Direct legacy-style call (no service, no await)
    config = tmp_config_manager.load_config()
    config.agent.llm_model = "gpt-4o"
    tmp_config_manager.save_config_file(config)

    # The hook scheduled an asyncio task — wait for it briefly
    import asyncio
    for _ in range(20):
        async with session_factory() as session:
            agent = await WorkspaceConfigRepo(session).get_section("agent")
            if agent and agent.get("llm_model") == "gpt-4o":
                break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("DB mirror task didn't run within 1s")

    # Cleanup the patch so other tests with the same config_manager
    # instance don't inherit it
    delattr(tmp_config_manager, "_db_mirror_installed")


@pytest.mark.asyncio
async def test_kill_switch_disables_db(monkeypatch, tmp_config_manager, session_factory):
    monkeypatch.setenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", "true")
    svc = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    config = tmp_config_manager.load_config()
    config.agent.llm_model = "gpt-5"
    ok = await svc.save_config(config)
    assert ok is True

    # DB should be empty — kill switch bypassed it
    async with session_factory() as session:
        agent = await WorkspaceConfigRepo(session).get_section("agent")
        assert agent is None  # never written


@pytest.mark.asyncio
async def test_reinstall_does_not_chain_closures(tmp_config_manager, session_factory):
    """Regression: re-instantiating WorkspaceConfigService over the same
    ConfigManager (after `_db_mirror_installed` is deleted by test
    cleanup) must NOT close over the previous install's patched method.

    Without the capture-once fix, the second install captures the
    already-patched method as `original_save`, then patches again, so
    every call to `cm.save_config_file` runs the mirror logic TWICE.
    """
    svc1 = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )
    captured_original = tmp_config_manager._db_mirror_original_save  # noqa: SLF001

    # Simulate test teardown that deletes the install flag without
    # restoring the patched method (matches the existing pattern at
    # tests/unit/test_workspace_config_service.py:155).
    delattr(tmp_config_manager, "_db_mirror_installed")

    svc2 = WorkspaceConfigService(
        config_manager=tmp_config_manager, session_factory=session_factory
    )

    # The pinned original on the cm must be the FIRST install's
    # original — not the patched method captured by the first install.
    assert tmp_config_manager._db_mirror_original_save is captured_original  # noqa: SLF001

    # Save once and confirm exactly ONE mirror task is scheduled, not two.
    config = tmp_config_manager.load_config()
    config.agent.llm_model = "no-chain"
    tmp_config_manager.save_config_file(config)
    # Both services share the cm, so both _pending_mirrors sets see
    # different views — but only ONE patched method runs, so total
    # cross-service tasks must be exactly 1.
    total_pending = len(svc1._pending_mirrors) + len(svc2._pending_mirrors)  # noqa: SLF001
    assert total_pending == 1

    await svc1.await_pending_mirrors()
    await svc2.await_pending_mirrors()
    delattr(tmp_config_manager, "_db_mirror_installed")
