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
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
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
NATIVE_CHAT_HISTORY_JSON_TO_DB_V1 = "native_chat_history_json_to_db_v1"
LANGFLOW_HISTORY_TO_NATIVE_V1 = "langflow_history_to_native_v1"


class RuntimeMigrationError(RuntimeError):
    """Raised when a required startup data migration fails."""


async def _already_done(session: AsyncSession, name: str) -> bool:
    row = await session.get(MigrationStatus, name)
    return row is not None


async def _mark_done(session: AsyncSession, name: str, notes: str = "") -> None:
    session.add(MigrationStatus(name=name, completed_at=datetime.now(UTC), notes=notes))
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


def _parse_legacy_dt(value: str | None) -> datetime | None:
    """Parse a legacy ISO datetime string, coercing naive values to UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def _migrate_legacy_native_conversation(
    native_repo: Any, user_id: str, response_id: str, metadata: dict[str, Any]
) -> bool:
    """Copy one legacy ``/chat`` conversation and its recoverable messages."""
    if await native_repo.get_conversation(response_id) is not None:
        return False
    created = _parse_legacy_dt(metadata.get("created_at"))
    last = _parse_legacy_dt(metadata.get("last_activity"))
    conversation = await native_repo.create_conversation(
        conversation_id=response_id,
        user_id=user_id,
        title=metadata.get("title"),
        filter_id=metadata.get("filter_id"),
        total_messages=0,
        created_at=created,
        last_activity=last,
    )
    legacy_messages = metadata.get("messages")
    if isinstance(legacy_messages, list):
        for message in legacy_messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if (
                not isinstance(role, str)
                or role not in {"user", "assistant"}
                or not isinstance(content, str)
            ):
                continue
            event_data: dict[str, Any] = {}
            if isinstance(message.get("chunks"), list):
                event_data["chunks"] = message["chunks"]
            response_data = message.get("response_data")
            if isinstance(response_data, dict) and response_data.get("usage"):
                event_data["usage"] = response_data["usage"]
            history_message = (
                ModelRequest(parts=[UserPromptPart(content=content)])
                if role == "user"
                else ModelResponse(parts=[TextPart(content=content)])
            )
            event_data["pydantic_messages"] = json.loads(
                ModelMessagesTypeAdapter.dump_json([history_message])
            )
            await native_repo.append_message(
                conversation=conversation,
                role=role,
                content=content,
                event_data=event_data,
                error=bool(message.get("error")),
            )
    conversation.total_messages = max(
        conversation.total_messages, int(metadata.get("total_messages") or 0)
    )
    conversation.last_activity = last or conversation.last_activity
    native_repo.session.add(conversation)
    await native_repo.session.flush()
    return True


async def migrate_legacy_native_chat_history_json_to_db(session: AsyncSession) -> int:
    """Move legacy ``/chat`` records even when the broader JSON migration ran."""
    from db.repositories import ChatHistoryRepo

    payload = await _read_json(get_data_file("conversations.json"))
    if not isinstance(payload, dict):
        return 0
    native_repo = ChatHistoryRepo(session)
    inserted = 0
    for user_id, conversations in payload.items():
        if not isinstance(conversations, dict):
            continue
        for response_id, metadata in conversations.items():
            if not isinstance(metadata, dict) or metadata.get("endpoint") != "chat":
                continue
            if await _migrate_legacy_native_conversation(
                native_repo, str(user_id), str(response_id), metadata
            ):
                inserted += 1
    return inserted


async def migrate_chat_history_json_to_db(session: AsyncSession) -> dict[str, int]:
    """Copy ``data/session_ownership.json`` and ``data/conversations.json``
    into the DB. Idempotent — only inserts rows that aren't already present.

    Returns a small stats dict for the migration_status notes column.
    """
    from db.repositories import ChatHistoryRepo, ConversationRepo, SessionOwnershipRepo

    stats = {"sessions_inserted": 0, "conversations_inserted": 0, "native_conversations": 0}

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
            created = _parse_legacy_dt(data.get("created_at"))
            last = _parse_legacy_dt(data.get("last_accessed"))
            inserted = await repo.upsert_raw(
                response_id=str(sid),
                user_id=str(uid),
                created_at=created,
                last_accessed=last,
                conversation_id=data.get("conversation_id") or str(sid),
            )
            if inserted:
                stats["sessions_inserted"] += 1

    # --- conversations.json -------------------------------------------
    conv_payload = await _read_json(get_data_file("conversations.json"))
    if isinstance(conv_payload, dict):
        crepo = ConversationRepo(session)
        native_repo = ChatHistoryRepo(session)
        for uid, user_convs in conv_payload.items():
            if not isinstance(user_convs, dict):
                continue
            for resp_id, meta in user_convs.items():
                if not isinstance(meta, dict):
                    continue
                # Before native history had its own tables, the legacy `/chat`
                # endpoint shared conversations.json with Langflow. Preserve
                # those records in the source that now serves `/chat/history`.
                if meta.get("endpoint") == "chat":
                    if await _migrate_legacy_native_conversation(
                        native_repo, str(uid), str(resp_id), meta
                    ):
                        stats["native_conversations"] += 1
                    continue
                created = _parse_legacy_dt(meta.get("created_at"))
                last = _parse_legacy_dt(meta.get("last_activity"))
                if await crepo.get(str(resp_id)) is not None:
                    continue
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


async def migrate_langflow_history_to_native(
    session: AsyncSession,
    fetch_messages: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
) -> dict[str, int]:
    """Copy Langflow's remote message history into OpenRAG's native tables.

    ``langflow_conversations`` has always held sidebar metadata only. This
    migration fetches the message bodies from Langflow's monitor API and makes
    the native tables the durable history source. Failed remote requests leave
    their metadata intact and are retried on the next startup.
    """
    from db.repositories import ChatHistoryRepo, ConversationRepo, SessionOwnershipRepo
    from services.langflow_history_service import langflow_history_service
    from services.native_chat_history_service import NativeChatHistoryService

    fetch = fetch_messages or langflow_history_service.fetch_session_messages
    legacy_repo = ConversationRepo(session)
    native_repo = ChatHistoryRepo(session)
    ownership_repo = SessionOwnershipRepo(session)
    stats = {"conversations": 0, "messages": 0, "failed": 0}

    for legacy in await legacy_repo.list_all():
        try:
            messages = await fetch(legacy.response_id)
            await NativeChatHistoryService.sync_langflow_conversation_in_session(
                native_repo,
                conversation_id=legacy.response_id,
                user_id=legacy.user_id,
                title=legacy.title,
                filter_id=legacy.filter_id,
                total_messages=legacy.total_messages or 0,
                created_at=legacy.created_at,
                last_activity=legacy.last_activity,
                messages=messages,
            )
            await ownership_repo.upsert_raw(
                response_id=legacy.response_id,
                user_id=legacy.user_id,
                created_at=legacy.created_at,
                last_accessed=legacy.last_activity,
            )
            stats["conversations"] += 1
            stats["messages"] += sum(
                1
                for message in messages
                if message.get("role") in {"user", "assistant"}
                and isinstance(message.get("content"), str)
            )
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            logger.warning(
                "langflow_history_to_native_v1: conversation import failed",
                conversation_id=legacy.response_id,
                error=str(exc),
            )

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
            f"sessions={stats['sessions_inserted']},"
            f"conversations={stats['conversations_inserted']},"
            f"native_conversations={stats['native_conversations']}"
        )
        await _mark_done(session, CHAT_HISTORY_JSON_TO_DB_V1, notes=notes)
        logger.info("chat_history_json_to_db_v1 completed", **stats)

    # This own marker intentionally runs after the original broad migration.
    # Deployments that completed it before native history was introduced still
    # need their legacy `/chat` records copied into the native tables.
    if not await _already_done(session, NATIVE_CHAT_HISTORY_JSON_TO_DB_V1):
        try:
            inserted = await migrate_legacy_native_chat_history_json_to_db(session)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "native_chat_history_json_to_db_v1 failed; aborting startup", error=str(exc)
            )
            raise RuntimeMigrationError(f"{NATIVE_CHAT_HISTORY_JSON_TO_DB_V1} failed") from exc
        await _mark_done(
            session, NATIVE_CHAT_HISTORY_JSON_TO_DB_V1, notes=f"conversations={inserted}"
        )
        logger.info("native_chat_history_json_to_db_v1 completed", conversations=inserted)

    if not await _already_done(session, LANGFLOW_HISTORY_TO_NATIVE_V1):
        stats = await migrate_langflow_history_to_native(session)
        if stats["failed"]:
            logger.warning(
                "langflow_history_to_native_v1 incomplete; retrying next startup",
                **stats,
            )
        else:
            notes = f"conversations={stats['conversations']},messages={stats['messages']}"
            await _mark_done(session, LANGFLOW_HISTORY_TO_NATIVE_V1, notes=notes)
            logger.info("langflow_history_to_native_v1 completed", **stats)

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
