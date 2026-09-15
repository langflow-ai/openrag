from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from config.paths import get_data_file
from config.storage_mode import (
    db_writes_enabled,
    file_writes_enabled,
    get_storage_mode,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ConversationPersistenceService:
    """Per-user chat-history index. Stores metadata only."""

    def __init__(
        self,
        storage_file: str | None = None,
        session_factory: Callable | None = None,
    ):
        self.storage_file = storage_file or get_data_file("conversations.json")
        os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()  # Serializes file writes
        self._session_factory = session_factory
        self._conversations: dict[str, dict[str, Any]] = self._load_conversations()

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    def _load_conversations(self) -> dict[str, dict[str, Any]]:
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, encoding="utf-8") as f:
                    data = json.load(f)

                # Validate top-level structure
                if not isinstance(data, dict):
                    logger.warning("Conversations file top-level is not a dict, resetting")
                    return {}

                # Validate and clean user buckets and conversation payloads
                cleaned = {}
                for user_id, user_convs in data.items():
                    if not isinstance(user_convs, dict):
                        logger.warning(f"User bucket for {user_id} is not a dict, skipping")
                        continue

                    valid_convs = {}
                    for response_id, payload in user_convs.items():
                        if not isinstance(payload, dict):
                            logger.warning(
                                f"Payload for {user_id}/{response_id} is not a dict, skipping"
                            )
                            continue
                        valid_convs[response_id] = payload

                    if valid_convs:
                        cleaned[user_id] = valid_convs

                return cleaned
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error loading conversations: {exc}")
                return {}
        return {}

    def _save_conversations_sync(self) -> None:
        # Acquire _save_lock first to serialize all saves, then snapshot under self.lock
        # This ensures queued saves commit in snapshot order and cannot overwrite newer data
        with self._save_lock:
            with self.lock:
                snapshot = copy.deepcopy(self._conversations)
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(
                    snapshot,
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )

    async def _save_conversations(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_conversations_sync)

    def _serialize_datetime(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: self._serialize_datetime(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._serialize_datetime(x) for x in obj]
        return obj

    def _count_total(self, data: dict[str, Any]) -> int:
        total = 0
        for user_conv in data.values():
            if isinstance(user_conv, dict):
                total += len(user_conv)
        return total

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_user_conversations(self, user_id: str) -> dict[str, Any]:
        mode = get_storage_mode()
        if mode == "files":
            with self.lock:
                if user_id not in self._conversations:
                    self._conversations[user_id] = {}
                return dict(self._conversations[user_id])

        # db / hybrid — DB read first
        db_payload = await self._db_get_for_user(user_id)
        if mode == "db":
            return db_payload

        # hybrid — merge JSON entries that aren't yet in DB
        merged = dict(db_payload)
        with self.lock:
            for resp_id, payload in self._conversations.get(user_id, {}).items():
                merged.setdefault(resp_id, payload)
        return merged

    async def store_conversation_thread(
        self,
        user_id: str,
        response_id: str,
        conversation_state: dict[str, Any],
    ) -> None:
        serialized = self._serialize_datetime(conversation_state)

        if file_writes_enabled():
            with self.lock:
                if user_id not in self._conversations:
                    self._conversations[user_id] = {}
                self._conversations[user_id][response_id] = serialized
            await self._save_conversations()

        if db_writes_enabled():
            await self._db_upsert(user_id, response_id, serialized)

    async def get_conversation_thread(self, user_id: str, response_id: str) -> dict[str, Any]:
        mode = get_storage_mode()
        if mode != "files":
            payload = await self._db_get_one(response_id, user_id)
            if payload is not None:
                return payload
            if mode == "db":
                return {}
        # files or hybrid-with-no-db-row → JSON
        return self._conversations.get(user_id, {}).get(response_id, {})

    async def delete_conversation_thread(self, user_id: str, response_id: str) -> bool:
        deleted = False

        if file_writes_enabled():
            file_deleted = False
            with self.lock:
                if user_id in self._conversations and response_id in self._conversations[user_id]:
                    del self._conversations[user_id][response_id]
                    file_deleted = True
            if file_deleted:
                await self._save_conversations()
                deleted = True

        if db_writes_enabled():
            db_deleted = await self._db_delete(response_id, user_id)
            deleted = deleted or db_deleted

        return deleted

    async def clear_user_conversations(self, user_id: str) -> None:
        cleared = False
        if file_writes_enabled():
            with self.lock:
                if user_id in self._conversations:
                    del self._conversations[user_id]
                    cleared = True
            if cleared:
                await self._save_conversations()

        if db_writes_enabled():
            await self._db_delete_all(user_id)

    async def prune_stale_conversations(self, ttl_days: int) -> int:
        """Hard-delete conversations whose last activity is older than the TTL."""
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        deleted = 0

        if file_writes_enabled():
            file_deleted = 0
            # Create snapshot of deletions under lock, then persist
            with self.lock:
                for user_id in list(self._conversations):
                    conversations = self._conversations[user_id]
                    for response_id, payload in list(conversations.items()):
                        if not isinstance(payload, dict):
                            continue
                        raw_last_activity = payload.get("last_activity") or payload.get(
                            "created_at"
                        )
                        if not raw_last_activity:
                            continue
                        try:
                            last_activity = datetime.fromisoformat(
                                str(raw_last_activity).replace("Z", "+00:00")
                            )
                            if last_activity.tzinfo is None:
                                last_activity = last_activity.replace(tzinfo=UTC)
                        except (TypeError, ValueError):
                            continue
                        if last_activity < cutoff:
                            del conversations[response_id]
                            file_deleted += 1
                    if not conversations:
                        del self._conversations[user_id]
            # Propagate save failure
            await self._save_conversations()
            deleted += file_deleted

        if db_writes_enabled():
            db_deleted = await self._db_delete_older_than(cutoff)
            deleted += db_deleted

        return deleted

    async def get_storage_stats(self) -> dict[str, Any]:
        # Snapshot — uses whichever storage the mode prioritizes.
        mode = get_storage_mode()
        if mode == "files":
            return {
                "total_users": len(self._conversations),
                "total_conversations": self._count_total(self._conversations),
                "storage_file": self.storage_file,
                "file_exists": os.path.exists(self.storage_file),
            }
        # db / hybrid summary from DB
        try:
            from sqlalchemy import distinct, func, select
            from sqlmodel import col

            from db.models import Conversation

            sess_factory = self._resolve_session_factory()
            if sess_factory is None:
                return {"total_users": 0, "total_conversations": 0}
            async with sess_factory() as session:
                total = (
                    await session.execute(select(func.count(col(Conversation.response_id))))
                ).scalar_one()
                users = (
                    await session.execute(select(func.count(distinct(col(Conversation.user_id)))))
                ).scalar_one()
            return {
                "total_users": int(users or 0),
                "total_conversations": int(total or 0),
                "storage_file": self.storage_file,
                "file_exists": os.path.exists(self.storage_file),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversation stats DB read failed", error=str(exc))
            return {"total_users": 0, "total_conversations": 0}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_session_factory(self):
        if self._session_factory is not None:
            return self._session_factory
        try:
            from db.engine import SessionLocal

            return SessionLocal
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _payload_from_row(row) -> dict[str, Any]:
        return {
            "response_id": row.response_id,
            "title": row.title,
            "endpoint": row.endpoint,
            "previous_response_id": row.previous_response_id,
            "filter_id": row.filter_id,
            "total_messages": row.total_messages or 0,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_activity": row.last_activity.isoformat() if row.last_activity else None,
        }

    async def _db_upsert(self, user_id: str, response_id: str, payload: dict[str, Any]) -> None:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return
        try:
            async with sess_factory() as session:
                repo = ConversationRepo(session)
                await repo.upsert(
                    response_id=response_id,
                    user_id=user_id,
                    title=payload.get("title"),
                    endpoint=payload.get("endpoint"),
                    previous_response_id=payload.get("previous_response_id"),
                    filter_id=payload.get("filter_id"),
                    total_messages=int(payload.get("total_messages") or 0),
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("DB store_conversation failed", error=str(exc))

    async def _db_get_for_user(self, user_id: str) -> dict[str, dict[str, Any]]:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return {}
        try:
            async with sess_factory() as session:
                rows = await ConversationRepo(session).list_for_user(user_id)
            return {r.response_id: self._payload_from_row(r) for r in rows}
        except Exception as exc:  # noqa: BLE001
            logger.debug("DB get_for_user failed", error=str(exc))
            return {}

    async def _db_get_one(self, response_id: str, user_id: str) -> dict[str, Any] | None:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return None
        try:
            async with sess_factory() as session:
                row = await ConversationRepo(session).get(response_id)
            if row is None or row.user_id != user_id:
                return None
            return self._payload_from_row(row)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DB get_one failed", error=str(exc))
            return None

    async def _db_delete(self, response_id: str, user_id: str) -> bool:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return False
        try:
            async with sess_factory() as session:
                ok = await ConversationRepo(session).delete(response_id, user_id)
                await session.commit()
                return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("DB delete failed", error=str(exc))
            return False

    async def _db_delete_older_than(self, cutoff: datetime) -> int:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return 0
        try:
            async with sess_factory() as session:
                deleted = await ConversationRepo(session).delete_older_than(cutoff)
                await session.commit()
                return deleted
        except Exception as exc:  # noqa: BLE001
            logger.error("DB stale conversation pruning failed", error=str(exc))
            return 0

    async def _db_delete_all(self, user_id: str) -> int:
        from db.repositories import ConversationRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return 0
        try:
            async with sess_factory() as session:
                n = await ConversationRepo(session).delete_all_for_user(user_id)
                await session.commit()
                return n
        except Exception as exc:  # noqa: BLE001
            logger.error("DB delete_all failed", error=str(exc))
            return 0


# Global instance — session_factory plumbed in main.py at startup.
conversation_persistence = ConversationPersistenceService()
