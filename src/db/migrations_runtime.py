"""Runtime migrations from legacy JSON state and the RBAC catalog.

These run on application startup AFTER Alembic upgrade. Legacy JSON
migrations are one-shot; idempotency is recorded in `migration_status`.
RBAC catalog sync (`db.seed.seed_roles_and_permissions`) runs every boot
and is additive-only.

Phase 1 only migrates *user identity* — connections.json, conversations.json,
and config.yaml are left in place. The legacy users get a placeholder row
with `oauth_provider='legacy'`. The next time they sign in via Google /
IBM, `user_service.ensure_user_row` matches on `email_lookup_hash` and
upgrades the row in place, preserving the original user_id so all
existing JSON references stay valid.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.paths import get_data_file
from db.models import MigrationStatus
from db.models import User as UserRow
from db.repositories._helpers import email_lookup_hash
from utils.encryption import read_encrypted_file
from utils.logging_config import get_logger

logger = get_logger(__name__)

JSON_TO_DB_V1 = "json_to_db_v1"
# Reserved (do not reuse): "cleanup_test_fixtures_v1" was a one-shot
# migration that DELETEd users with id IN ('admin-sub','dev-sub',...)
# — removed because those plain strings could plausibly collide with
# real OAuth subjects in IBM AMS deployments. Test pollution is now
# prevented at source by tests/unit/conftest.py forcing in-memory
# SQLite, so there's no longer dirty data to sweep.
CONFIG_YAML_TO_DB_V1 = "config_yaml_to_db_v1"
CHAT_HISTORY_JSON_TO_DB_V1 = "chat_history_json_to_db_v1"


class RuntimeMigrationError(RuntimeError):
    """Raised when a required startup data migration fails."""


async def _already_done(session: AsyncSession, name: str) -> bool:
    row = await session.get(MigrationStatus, name)
    return row is not None


async def _mark_done(session: AsyncSession, name: str, notes: str = "") -> None:
    session.add(MigrationStatus(name=name, completed_at=datetime.utcnow(), notes=notes))
    await session.flush()


async def _read_json(path: str):
    if not os.path.exists(path):
        return None
    raw, _ = await read_encrypted_file(path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Skipping malformed JSON during migration", path=path)
        return None


def _user_ids_from_connections(payload) -> Iterable[str]:
    if not payload:
        return []
    items = payload.get("connections", []) if isinstance(payload, dict) else payload
    out = []
    for c in items or []:
        if isinstance(c, dict) and c.get("user_id"):
            out.append(str(c["user_id"]))
    return out


def _user_ids_from_conversations(payload) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    return [k for k in payload.keys() if isinstance(k, str)]


def _user_ids_from_session_ownership(payload) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    out = []
    for v in payload.values():
        if isinstance(v, dict):
            uid = v.get("user_id")
            if uid:
                out.append(str(uid))
        elif isinstance(v, str):
            out.append(v)
    return out


async def migrate_legacy_users(session: AsyncSession) -> int:
    """Insert legacy/* users discovered in JSON files. Returns insert count."""
    seen: set[str] = set()
    sources = [
        ("connections.json", _user_ids_from_connections),
        ("conversations.json", _user_ids_from_conversations),
        ("session_ownership.json", _user_ids_from_session_ownership),
    ]
    for filename, extract in sources:
        payload = await _read_json(get_data_file(filename))
        if payload is None:
            continue
        for uid in extract(payload):
            if uid:
                seen.add(uid)

    if not seen:
        return 0

    inserted = 0
    for legacy_id in seen:
        # Email is unknown for legacy rows; use a synthetic placeholder so we
        # still have *some* lookup hash. Real merge happens on next sign-in.
        synth_email = f"{legacy_id}@unknown.local"
        row = UserRow(
            id=legacy_id,
            oauth_provider="legacy",
            oauth_subject=legacy_id,
            email=synth_email,
            email_lookup_hash=email_lookup_hash(synth_email),
            display_name=legacy_id,
        )
        # SAVEPOINT per row so a duplicate (e.g. another runner already
        # inserted this legacy id) only rolls back THIS row, not the
        # whole outer transaction with previously inserted legacy users.
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            inserted += 1
        except IntegrityError:
            # Some other run beat us to it; savepoint rolled back
            # automatically — outer transaction and prior inserts intact.
            continue
    return inserted


async def migrate_config_yaml_to_db(session: AsyncSession) -> int:
    """Copy what ``config.yaml`` holds today into the ``workspace_config``
    table. Idempotent.

    Returns the number of section rows written. Zero is fine — means the
    workspace has no config.yaml yet (fresh install) and the table will
    fill up the first time an admin completes onboarding.
    """
    from db.repositories import WorkspaceConfigRepo
    from utils.encryption import encrypt_secret

    # Read the current yaml-backed config exactly the way the legacy
    # ConfigManager does (decrypts api_keys, applies env overrides, etc.).
    try:
        from config.config_manager import config_manager

        config = config_manager.load_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("config_yaml_to_db_v1: load_config() failed; skipping", error=str(exc))
        return 0

    config_dict = config.to_dict()
    providers = dict(config_dict.get("providers", {}))
    for prov_name, prov_data in providers.items():
        if isinstance(prov_data, dict) and prov_data.get("api_key"):
            # Re-encrypt with the JSON envelope so the DB row matches
            # what config.yaml stores on disk.
            prov_data["api_key"] = encrypt_secret(prov_data["api_key"])
        providers[prov_name] = prov_data

    sections = {
        "providers": providers,
        "knowledge": config_dict.get("knowledge", {}),
        "agent": config_dict.get("agent", {}),
        "onboarding": config_dict.get("onboarding", {}),
        "meta": {"edited": bool(config_dict.get("edited", False))},
    }

    repo = WorkspaceConfigRepo(session)
    written = 0
    for section, value in sections.items():
        await repo.upsert(section, value)
        written += 1
    return written


async def migrate_chat_history_json_to_db(session: AsyncSession) -> dict[str, int]:
    """Copy ``data/session_ownership.json`` and ``data/conversations.json``
    into the DB. Idempotent — only inserts rows that aren't already present.

    Returns a small stats dict for the migration_status notes column.
    """
    from db.repositories import ConversationRepo, SessionOwnershipRepo

    stats = {"sessions_inserted": 0, "conversations_inserted": 0}

    # --- session_ownership.json ---------------------------------------
    so_payload = await _read_json(get_data_file("session_ownership.json"))
    if isinstance(so_payload, dict):
        repo = SessionOwnershipRepo(session)
        for sid, data in so_payload.items():
            if not isinstance(data, dict):
                continue
            uid = data.get("user_id")
            if not uid:
                continue
            try:
                created = (
                    datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                )
            except Exception:  # noqa: BLE001
                created = None
            try:
                last = (
                    datetime.fromisoformat(data["last_accessed"])
                    if data.get("last_accessed")
                    else None
                )
            except Exception:  # noqa: BLE001
                last = None
            inserted = await repo.upsert_raw(
                response_id=str(sid),
                user_id=str(uid),
                created_at=created,
                last_accessed=last,
            )
            if inserted:
                stats["sessions_inserted"] += 1

    # --- conversations.json -------------------------------------------
    conv_payload = await _read_json(get_data_file("conversations.json"))
    if isinstance(conv_payload, dict):
        crepo = ConversationRepo(session)
        for uid, user_convs in conv_payload.items():
            if not isinstance(user_convs, dict):
                continue
            for resp_id, meta in user_convs.items():
                if not isinstance(meta, dict):
                    continue
                if await crepo.get(str(resp_id)) is not None:
                    continue
                try:
                    created = (
                        datetime.fromisoformat(meta["created_at"])
                        if meta.get("created_at")
                        else None
                    )
                except Exception:  # noqa: BLE001
                    created = None
                try:
                    last = (
                        datetime.fromisoformat(meta["last_activity"])
                        if meta.get("last_activity")
                        else None
                    )
                except Exception:  # noqa: BLE001
                    last = None
                await crepo.upsert(
                    response_id=str(resp_id),
                    user_id=str(uid),
                    title=meta.get("title"),
                    endpoint=meta.get("endpoint"),
                    previous_response_id=meta.get("previous_response_id"),
                    filter_id=meta.get("filter_id"),
                    total_messages=int(meta.get("total_messages") or 0),
                    created_at=created,
                    last_activity=last,
                )
                stats["conversations_inserted"] += 1

    return stats


async def run(session: AsyncSession) -> None:
    """Top-level entry. Caller is responsible for committing."""
    if not await _already_done(session, JSON_TO_DB_V1):
        inserted = 0
        try:
            inserted = await migrate_legacy_users(session)
        except Exception as exc:  # noqa: BLE001
            logger.error("JSON->DB migration failed; aborting startup", error=str(exc))
            raise RuntimeMigrationError(f"{JSON_TO_DB_V1} failed") from exc
        await _mark_done(session, JSON_TO_DB_V1, notes=f"legacy_users_inserted={inserted}")
        logger.info("JSON->DB migration completed", inserted=inserted)

    if not await _already_done(session, CONFIG_YAML_TO_DB_V1):
        try:
            written = await migrate_config_yaml_to_db(session)
        except Exception as exc:  # noqa: BLE001
            logger.error("config_yaml_to_db_v1 failed; aborting startup", error=str(exc))
            raise RuntimeMigrationError(f"{CONFIG_YAML_TO_DB_V1} failed") from exc
        await _mark_done(session, CONFIG_YAML_TO_DB_V1, notes=f"sections_written={written}")
        logger.info("config_yaml_to_db_v1 completed", sections_written=written)

    if not await _already_done(session, CHAT_HISTORY_JSON_TO_DB_V1):
        try:
            stats = await migrate_chat_history_json_to_db(session)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "chat_history_json_to_db_v1 failed; aborting startup",
                error=str(exc),
            )
            raise RuntimeMigrationError(f"{CHAT_HISTORY_JSON_TO_DB_V1} failed") from exc
        notes = (
            f"sessions={stats['sessions_inserted']},conversations={stats['conversations_inserted']}"
        )
        await _mark_done(session, CHAT_HISTORY_JSON_TO_DB_V1, notes=notes)
        logger.info("chat_history_json_to_db_v1 completed", **stats)

    try:
        from db.seed import seed_roles_and_permissions

        await seed_roles_and_permissions(session)
    except Exception as exc:  # noqa: BLE001
        logger.error("RBAC catalog sync failed; aborting startup", error=str(exc))
        raise RuntimeMigrationError("rbac_catalog_sync failed") from exc


# ---------------------------------------------------------------------------
# Alembic upgrade — programmatic invocation
# ---------------------------------------------------------------------------


def run_alembic_upgrade(target: str = "head") -> None:
    """Run `alembic upgrade <target>` programmatically.

    Internally Alembic's env.py spins up its own asyncio.run loop, so this
    function MUST NOT be invoked from inside an already-running event
    loop. Async callers should use `run_alembic_upgrade_async` instead.
    """
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parent.parent.parent
    cfg_path = root / "alembic.ini"
    if not cfg_path.exists():
        logger.warning("alembic.ini not found; skipping schema upgrade", path=str(cfg_path))
        return

    cfg = Config(str(cfg_path))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, target)


async def run_alembic_upgrade_async(target: str = "head") -> None:
    """Async-safe wrapper. Runs the sync alembic command in a worker thread.

    Necessary because `alembic/env.py` uses `asyncio.run(...)` internally,
    which fails when invoked from a running loop.
    """
    import asyncio

    await asyncio.to_thread(run_alembic_upgrade, target)
