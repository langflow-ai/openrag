"""Conversation persistence — chat-history metadata only (full message
bodies live in Langflow).

Mode-aware (``OPENRAG_STORAGE_MODE`` from ``src/config/storage_mode.py``):

| Mode         | Reads                | Writes              |
|--------------|----------------------|---------------------|
| db (default) | DB only              | DB only — no JSON   |
| hybrid       | DB → JSON fallback   | DB + JSON dual      |
| files        | JSON only            | JSON only           |

All public methods are async. Call sites in ``src/agent.py`` were
flipped from sync to ``await`` as part of this migration.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

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
        storage_file: Optional[str] = None,
        session_factory: Optional[Callable] = None,
    ):
        self.storage_file = storage_file or get_data_file("conversations.json")
        os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
        self.lock = threading.Lock()
        self._session_factory = session_factory
        self._conversations: Dict[str, Dict[str, Any]] = self._load_conversations()

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    def _load_conversations(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error loading conversations: {exc}")
                return {}
        return {}

    def _save_conversations_sync(self) -> None:
        try:
            with self.lock:
                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump(
                        self._conversations,
                        f,
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error saving conversations: {exc}")

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

    def _count_total(self, data: Dict[str, Any]) -> int:
        total = 0
        for user_conv in data.values():
            if isinstance(user_conv, dict):
                total += len(user_conv)
        return total

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_user_conversations(self, user_id: str) -> Dict[str, Any]:
        mode = get_storage_mode()
        if mode == "files":
            if user_id not in self._conversations:
                self._conversations[user_id] = {}
            return self._conversations[user_id]

        # db / hybrid — DB read first
        db_payload = await self._db_get_for_user(user_id)
        if mode == "db":
            return db_payload

        # hybrid — merge JSON entries that aren't yet in DB
        merged = dict(db_payload)
        for resp_id, payload in self._conversations.get(user_id, {}).items():
            merged.setdefault(resp_id, payload)
        return merged

    async def store_conversation_thread(
        self,
        user_id: str,
        response_id: str,
        conversation_state: Dict[str, Any],
    ) -> None:
        serialized = self._serialize_datetime(conversation_state)

        if file_writes_enabled():
            if user_id not in self._conversations:
                self._conversations[user_id] = {}
            self._conversations[user_id][response_id] = serialized
            await self._save_conversations()

        if db_writes_enabled():
            await self._db_upsert(user_id, response_id, serialized)

    async def get_conversation_thread(
        self, user_id: str, response_id: str
    ) -> Dict[str, Any]:
        mode = get_storage_mode()
        if mode != "files":
            payload = await self._db_get_one(response_id, user_id)
            if payload is not None:
                return payload
            if mode == "db":
                return {}
        # files or hybrid-with-no-db-row → JSON
        return self._conversations.get(user_id, {}).get(response_id, {})

    async def delete_conversation_thread(
        self, user_id: str, response_id: str
    ) -> bool:
        deleted = False

        if file_writes_enabled():
            if (
                user_id in self._conversations
                and response_id in self._conversations[user_id]
            ):
                del self._conversations[user_id][response_id]
                await self._save_conversations()
                deleted = True

        if db_writes_enabled():
            db_deleted = await self._db_delete(response_id, user_id)
            deleted = deleted or db_deleted

        return deleted

    async def clear_user_conversations(self, user_id: str) -> None:
        if file_writes_enabled() and user_id in self._conversations:
            del self._conversations[user_id]
            await self._save_conversations()

        if db_writes_enabled():
            await self._db_delete_all(user_id)

    async def get_storage_stats(self) -> Dict[str, Any]:
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
            from db.models import Conversation
            from sqlalchemy import select, func

            sess_factory = self._resolve_session_factory()
            if sess_factory is None:
                return {"total_users": 0, "total_conversations": 0}
            async with sess_factory() as session:
                total = (
                    await session.execute(select(func.count(Conversation.response_id)))
                ).scalar_one()
                users = (
                    await session.execute(
                        select(func.count(func.distinct(Conversation.user_id)))
                    )
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
    def _payload_from_row(row) -> Dict[str, Any]:
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

    async def _db_upsert(
        self, user_id: str, response_id: str, payload: Dict[str, Any]
    ) -> None:
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

    async def _db_get_for_user(self, user_id: str) -> Dict[str, Dict[str, Any]]:
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

    async def _db_get_one(
        self, response_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
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
