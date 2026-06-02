"""API-only upgrade-path test for legacy file state -> SQL runtime migration."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import yaml
from sqlalchemy import func, select

_RELOAD_MODULES = [
    "api",
    "api.connector_router",
    "api.router",
    "app.container",
    "app.factory",
    "app.lifespan",
    "app.routes",
    "app.routes.internal",
    "auth_middleware",
    "config.settings",
    "dependencies",
    "main",
    "services",
    "services.conversation_persistence_service",
    "services.default_docs_service",
    "services.rbac_service",
    "services.search_service",
    "services.session_ownership_service",
    "services.startup_orchestrator",
    "utils.opensearch_init",
]

_RELOAD_PREFIXES = ("api.", "app.", "services.")


def _purge_reloaded_modules() -> None:
    for mod in list(sys.modules):
        if mod in _RELOAD_MODULES or mod.startswith(_RELOAD_PREFIXES):
            sys.modules.pop(mod, None)


@pytest_asyncio.fixture
async def legacy_migration_workspace(tmp_path: Path, monkeypatch):
    """Isolate config/data/DB paths and reset module singletons for one app boot."""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    keys_dir = tmp_path / "keys"
    data_dir.mkdir()
    config_dir.mkdir()
    keys_dir.mkdir()

    db_path = tmp_path / "openrag.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENRAG_DATA_PATH", str(data_dir))
    monkeypatch.setenv("OPENRAG_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv("OPENRAG_KEYS_PATH", str(keys_dir))
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", "db")
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")
    monkeypatch.setenv("OPENRAG_NOAUTH_ROLE", "admin")
    monkeypatch.setenv("DISABLE_STARTUP_INGEST", "true")
    monkeypatch.setenv("FETCH_OPENRAG_DOCS_AT_STARTUP", "false")

    from db.engine import dispose_engine as dispose_existing_engine

    await dispose_existing_engine()
    _purge_reloaded_modules()

    from config.config_manager import config_manager
    from db.engine import dispose_engine
    from dependencies import invalidate_user_ensured_cache
    from services.conversation_persistence_service import conversation_persistence
    from services.session_ownership_service import session_ownership_service

    old_config_file = config_manager.config_file
    old_config_cache = config_manager._config
    old_conversation_file = conversation_persistence.storage_file
    old_conversations = conversation_persistence._conversations
    old_ownership_file = session_ownership_service.ownership_file
    old_ownership_data = session_ownership_service.ownership_data
    old_conversation_session_factory = conversation_persistence._session_factory
    old_ownership_session_factory = session_ownership_service._session_factory

    await dispose_engine()
    invalidate_user_ensured_cache()
    config_manager.config_file = config_dir / "config.yaml"
    config_manager._config = None
    conversation_persistence.storage_file = str(data_dir / "conversations.json")
    conversation_persistence._conversations = {}
    conversation_persistence._session_factory = None
    session_ownership_service.ownership_file = str(data_dir / "session_ownership.json")
    session_ownership_service.ownership_data = {}
    session_ownership_service._session_factory = None

    _write_legacy_files(config_dir=config_dir, data_dir=data_dir)

    try:
        yield {
            "config_dir": config_dir,
            "data_dir": data_dir,
            "db_path": db_path,
        }
    finally:
        await dispose_engine()
        invalidate_user_ensured_cache()
        config_manager.config_file = old_config_file
        config_manager._config = old_config_cache
        conversation_persistence.storage_file = old_conversation_file
        conversation_persistence._conversations = old_conversations
        conversation_persistence._session_factory = old_conversation_session_factory
        session_ownership_service.ownership_file = old_ownership_file
        session_ownership_service.ownership_data = old_ownership_data
        session_ownership_service._session_factory = old_ownership_session_factory
        _purge_reloaded_modules()


def _write_legacy_files(*, config_dir: Path, data_dir: Path) -> None:
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "openai": {
                        "configured": True,
                        "api_key": "legacy-openai-key",
                    },
                    "anthropic": {},
                    "watsonx": {},
                    "ollama": {},
                },
                "knowledge": {
                    "embedding_model": "text-embedding-3-small",
                    "embedding_provider": "openai",
                    "chunk_size": 777,
                    "index_name": "documents",
                },
                "agent": {
                    "llm_model": "gpt-4o-mini",
                    "llm_provider": "openai",
                    "system_prompt": "legacy prompt",
                },
                "onboarding": {
                    "current_step": 4,
                    "openrag_docs_filter_id": "legacy-filter",
                },
                "edited": True,
            }
        ),
        encoding="utf-8",
    )

    (data_dir / "session_ownership.json").write_text(
        json.dumps(
            {
                "legacy-session": {
                    "user_id": "anonymous",
                    "created_at": "2026-04-01T10:00:00",
                    "last_accessed": "2026-04-02T11:00:00",
                },
                "other-session": {
                    "user_id": "legacy-owner",
                    "created_at": "2026-04-03T09:00:00",
                    "last_accessed": "2026-04-03T09:30:00",
                },
            }
        ),
        encoding="utf-8",
    )

    (data_dir / "conversations.json").write_text(
        json.dumps(
            {
                "anonymous": {
                    "legacy-session": {
                        "title": "Migrated chat",
                        "endpoint": "chat",
                        "previous_response_id": None,
                        "filter_id": "legacy-filter",
                        "total_messages": 3,
                        "created_at": "2026-04-01T10:00:00",
                        "last_activity": "2026-04-02T11:00:00",
                    }
                },
                "legacy-owner": {
                    "other-session": {
                        "title": "Other migrated chat",
                        "endpoint": "langflow",
                        "total_messages": 1,
                        "created_at": "2026-04-03T09:00:00",
                        "last_activity": "2026-04-03T09:30:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    (data_dir / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "connection_id": "legacy-connection",
                        "user_id": "legacy-owner",
                        "config": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


async def _build_and_start_app():
    """Run the same Alembic-before-app, runtime-migration-on-startup sequence."""
    from config.config_manager import config_manager
    from db.migrations_runtime import run_alembic_upgrade_async
    from main import create_app

    config_manager._config = None
    await run_alembic_upgrade_async("head")
    app = await create_app()
    await app.router.startup()
    return app


async def _shutdown_app(app) -> None:
    from db.engine import dispose_engine

    tasks = list(getattr(app.state, "background_tasks", set()))
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await app.router.shutdown()
    await dispose_engine()


async def _db_snapshot() -> dict[str, int]:
    from db.engine import SessionLocal
    from db.models import Conversation, MigrationStatus, SessionOwnership, User

    assert SessionLocal is not None
    async with SessionLocal() as session:
        users = await session.scalar(select(func.count()).select_from(User))
        conversations = await session.scalar(select(func.count()).select_from(Conversation))
        ownership = await session.scalar(select(func.count()).select_from(SessionOwnership))
        statuses = await session.scalar(select(func.count()).select_from(MigrationStatus))
    return {
        "users": int(users or 0),
        "conversations": int(conversations or 0),
        "ownership": int(ownership or 0),
        "statuses": int(statuses or 0),
    }


async def _assert_migrated_db_state() -> None:
    from db.engine import SessionLocal
    from db.migrations_runtime import (
        CHAT_HISTORY_JSON_TO_DB_V1,
        CONFIG_YAML_TO_DB_V1,
        JSON_TO_DB_V1,
    )
    from db.models import (
        Conversation,
        MigrationStatus,
        SessionOwnership,
        User,
        WorkspaceConfig,
    )

    assert SessionLocal is not None
    async with SessionLocal() as session:
        statuses = {
            row.name: row.notes
            for row in (await session.execute(select(MigrationStatus))).scalars().all()
        }
        assert JSON_TO_DB_V1 in statuses
        assert CONFIG_YAML_TO_DB_V1 in statuses
        assert CHAT_HISTORY_JSON_TO_DB_V1 in statuses

        meta = await session.get(WorkspaceConfig, "meta")
        onboarding = await session.get(WorkspaceConfig, "onboarding")
        knowledge = await session.get(WorkspaceConfig, "knowledge")
        assert meta is not None
        assert meta.value == {"edited": True}
        assert onboarding is not None
        assert onboarding.value["current_step"] == 4
        assert knowledge is not None
        assert knowledge.value["chunk_size"] == 777

        legacy_session = await session.get(SessionOwnership, "legacy-session")
        assert legacy_session is not None
        assert legacy_session.user_id == "anonymous"

        conversation = await session.get(Conversation, "legacy-session")
        assert conversation is not None
        assert conversation.user_id == "anonymous"
        assert conversation.title == "Migrated chat"
        assert conversation.total_messages == 3

        subjects = {
            row.oauth_subject
            for row in (await session.execute(select(User))).scalars().all()
            if row.oauth_provider == "legacy"
        }
        assert {"anonymous", "legacy-owner"}.issubset(subjects)


@pytest.mark.asyncio
@pytest.mark.usefixtures("legacy_migration_workspace")
async def test_legacy_file_state_migrates_on_backend_startup_and_is_idempotent():
    app = await _build_and_start_app()
    try:
        await _assert_migrated_db_state()
        first_snapshot = await _db_snapshot()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            onboarding = await client.get("/onboarding-status")
            assert onboarding.status_code == 200, onboarding.text
            assert onboarding.json() == {"onboarded": True, "current_step": 4}

            history = await client.get("/chat/history")
            assert history.status_code == 200, history.text
            conversations = {
                item["response_id"]: item for item in history.json().get("conversations", [])
            }
            assert conversations["legacy-session"]["title"] == "Migrated chat"
            assert conversations["legacy-session"]["total_messages"] == 3
    finally:
        await _shutdown_app(app)

    # A second backend boot against the same DB must not duplicate migrated rows.
    app = await _build_and_start_app()
    try:
        assert await _db_snapshot() == first_snapshot
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            onboarding = await client.get("/onboarding-status")
            assert onboarding.status_code == 200, onboarding.text
            assert onboarding.json()["onboarded"] is True
    finally:
        await _shutdown_app(app)
