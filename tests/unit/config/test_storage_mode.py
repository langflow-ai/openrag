"""WorkspaceConfigService — coverage for the 3 storage modes
(`hybrid`, `db`, `files`) selected by ``OPENRAG_STORAGE_MODE``.

The contract:

| Mode    | yaml created on save? | DB written? | yaml read fallback? |
|---------|-----------------------|-------------|---------------------|
| hybrid  | yes                   | yes         | yes                 |
| db      | NO                    | yes         | NO                  |
| files   | yes                   | NO          | yes                 |
"""

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
from config.storage_mode import (  # noqa: E402
    db_writes_enabled,
    file_writes_enabled,
    get_storage_mode,
)
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
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))
        yield cm


# ======================================================================
# Mode resolver
# ======================================================================


def test_default_mode_is_db(monkeypatch):
    monkeypatch.delenv("OPENRAG_STORAGE_MODE", raising=False)
    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)
    assert get_storage_mode() == "db"


def test_explicit_mode_db(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    assert get_storage_mode() == "db"
    assert db_writes_enabled() is True
    assert file_writes_enabled() is False


def test_explicit_mode_files(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    assert get_storage_mode() == "files"
    assert db_writes_enabled() is False
    assert file_writes_enabled() is True


def test_legacy_kill_switch_forces_files(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.setenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", "true")
    assert get_storage_mode() == "files"  # legacy switch wins


def test_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "weird")
    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)
    assert get_storage_mode() == "db"


# ======================================================================
# Save behavior per mode
# ======================================================================


@pytest.mark.asyncio
async def test_db_mode_does_not_create_yaml(monkeypatch, tmp_config_manager, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    config = tmp_config_manager.load_config()
    config.agent.system_prompt = "db-only test"

    ok = await svc.save_config(config)
    assert ok is True

    # Yaml file MUST NOT be created in db mode
    assert not tmp_config_manager.config_file.exists()

    # DB has the data
    async with session_factory() as session:
        agent = await WorkspaceConfigRepo(session).get_section("agent")
        assert agent and agent.get("system_prompt") == "db-only test"


@pytest.mark.asyncio
async def test_files_mode_does_not_write_db(monkeypatch, tmp_config_manager, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    config = tmp_config_manager.load_config()
    config.agent.system_prompt = "files-only test"

    ok = await svc.save_config(config)
    assert ok is True

    # Yaml created
    assert tmp_config_manager.config_file.exists()

    # DB untouched
    async with session_factory() as session:
        rows = await WorkspaceConfigRepo(session).list_all()
        assert rows == {}


@pytest.mark.asyncio
async def test_hybrid_mode_writes_both(monkeypatch, tmp_config_manager, session_factory):
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    config = tmp_config_manager.load_config()
    config.agent.system_prompt = "hybrid test"

    ok = await svc.save_config(config)
    assert ok is True

    assert tmp_config_manager.config_file.exists()
    async with session_factory() as session:
        agent = await WorkspaceConfigRepo(session).get_section("agent")
        assert agent and agent.get("system_prompt") == "hybrid test"


# ======================================================================
# Read behavior — db mode ignores yaml entirely
# ======================================================================


@pytest.mark.asyncio
async def test_db_mode_ignores_yaml_fallback(monkeypatch, tmp_config_manager, session_factory):
    """If yaml exists with edited=true but DB is empty, db mode must
    NOT report onboarded — it ignores yaml entirely."""
    # Seed yaml so the legacy ConfigManager would say edited=True
    cfg = tmp_config_manager.load_config()
    cfg.agent.system_prompt = "from yaml only"
    cfg.edited = True
    tmp_config_manager.save_config_file(cfg)
    assert tmp_config_manager.config_file.exists()

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    # DB is empty → db mode must say NOT onboarded
    assert await svc.is_onboarded() is False
    # And current_step has nothing to report
    assert await svc.get_onboarding_step() is None


@pytest.mark.asyncio
async def test_files_mode_reads_only_yaml(monkeypatch, tmp_config_manager, session_factory):
    """If DB has edited=true but yaml is empty, files mode must NOT
    report onboarded — DB is invisible to it."""
    async with session_factory() as session:
        await WorkspaceConfigRepo(session).upsert("meta", {"edited": True})
        await session.commit()

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    assert await svc.is_onboarded() is False


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_yaml_when_db_empty(
    monkeypatch, tmp_config_manager, session_factory
):
    """In hybrid: empty DB + populated yaml → reads yaml."""
    cfg = tmp_config_manager.load_config()
    cfg.edited = True
    tmp_config_manager.save_config_file(cfg)

    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "hybrid")
    svc = WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    assert await svc.is_onboarded() is True


# ======================================================================
# Monkey-patch hook respects mode
# ======================================================================


@pytest.mark.asyncio
async def test_db_mode_legacy_save_skips_yaml_writes(
    monkeypatch, tmp_config_manager, session_factory
):
    """A legacy caller that hits config_manager.save_config_file()
    directly should NOT create a yaml file in db mode."""
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    # Legacy-style call
    cfg = tmp_config_manager.load_config()
    cfg.agent.llm_model = "claude-sonnet-4-6"
    tmp_config_manager.save_config_file(cfg)

    # Wait briefly for the async DB mirror
    import asyncio

    for _ in range(20):
        async with session_factory() as session:
            agent = await WorkspaceConfigRepo(session).get_section("agent")
            if agent and agent.get("llm_model") == "claude-sonnet-4-6":
                break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("DB mirror task didn't run within 1s")

    # Critically: NO yaml file
    assert not tmp_config_manager.config_file.exists()

    delattr(tmp_config_manager, "_db_mirror_installed")


@pytest.mark.asyncio
async def test_files_mode_does_not_install_hooks(monkeypatch, tmp_config_manager, session_factory):
    """In files mode the monkey-patch must not be installed —
    legacy ``config_manager.save_config_file`` is left pristine."""
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "files")
    WorkspaceConfigService(config_manager=tmp_config_manager, session_factory=session_factory)
    assert not getattr(tmp_config_manager, "_db_mirror_installed", False)

    # And a direct legacy save creates yaml without scheduling a DB mirror.
    cfg = tmp_config_manager.load_config()
    cfg.agent.system_prompt = "files mode unhooked"
    tmp_config_manager.save_config_file(cfg)
    assert tmp_config_manager.config_file.exists()
    async with session_factory() as session:
        rows = await WorkspaceConfigRepo(session).list_all()
        assert rows == {}  # nothing mirrored — hook never ran
