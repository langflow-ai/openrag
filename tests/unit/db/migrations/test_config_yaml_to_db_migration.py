"""migrations_runtime.run — config_yaml_to_db_v1 step."""

import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.migrations_runtime import (  # noqa: E402
    CONFIG_YAML_TO_DB_V1,
    migrate_config_yaml_to_db,
)
from db.models import MigrationStatus  # noqa: E402
from db.repositories import WorkspaceConfigRepo  # noqa: E402


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


@pytest.fixture
def tmp_yaml(monkeypatch):
    """Point ConfigManager at an isolated temp directory for the test."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / "config"
        cfg_dir.mkdir()
        monkeypatch.setenv("OPENRAG_CONFIG_PATH", str(cfg_dir))
        # ConfigManager is a singleton at module level — reset its
        # internal state so it picks up the new path on next load.
        from config.config_manager import config_manager
        config_manager.config_file = cfg_dir / "config.yaml"
        config_manager._config = None
        yield cfg_dir / "config.yaml"


@pytest.mark.asyncio
async def test_migration_writes_all_sections_from_existing_yaml(
    tmp_yaml, session
):
    """Existing install with config.yaml → all sections copied to DB."""
    yaml_payload = {
        "providers": {
            "openai": {"configured": True},
            "anthropic": {},
            "watsonx": {},
            "ollama": {},
        },
        "knowledge": {"embedding_model": "text-embedding-3-small", "chunk_size": 1024},
        "agent": {"llm_model": "gpt-4o", "system_prompt": "be helpful"},
        "onboarding": {"current_step": "complete"},
        "edited": True,
    }
    tmp_yaml.write_text(yaml.safe_dump(yaml_payload))

    written = await migrate_config_yaml_to_db(session)
    await session.commit()
    assert written == 5  # providers, knowledge, agent, onboarding, meta

    repo = WorkspaceConfigRepo(session)
    assert (await repo.get_section("agent"))["llm_model"] == "gpt-4o"
    assert (await repo.get_section("knowledge"))["embedding_model"] == "text-embedding-3-small"
    assert (await repo.get_section("onboarding"))["current_step"] == "complete"
    assert (await repo.get_section("meta")) == {"edited": True}


@pytest.mark.asyncio
async def test_migration_fresh_install_writes_empty_sections(tmp_yaml, session):
    """No yaml file present — migration still runs, writes empty/default
    sections, edited=False."""
    # Don't create yaml file; ConfigManager.load_config returns defaults
    written = await migrate_config_yaml_to_db(session)
    await session.commit()
    assert written == 5

    repo = WorkspaceConfigRepo(session)
    meta = await repo.get_section("meta")
    assert meta == {"edited": False}


@pytest.mark.asyncio
async def test_migration_via_run_marks_status(tmp_yaml, session):
    """Calling migrations_runtime.run multiple times is idempotent."""
    from db.migrations_runtime import run

    await run(session)
    await session.commit()
    status = await session.get(MigrationStatus, CONFIG_YAML_TO_DB_V1)
    assert status is not None

    # Second run — no-op
    await run(session)
    await session.commit()
    # Still exists, single status row
    status2 = await session.get(MigrationStatus, CONFIG_YAML_TO_DB_V1)
    assert status2 is not None
