"""Session Ownership Service.

Tracks which user owns which chat session. Mode-aware:

| OPENRAG_STORAGE_MODE | Reads                          | Writes                |
|----------------------|--------------------------------|-----------------------|
| db (default)         | DB only — JSON ignored         | DB only — no JSON     |
| hybrid               | DB → JSON fallback             | DB + JSON dual-write  |
| files (legacy)       | JSON only                      | JSON only             |

All public methods are async. Call sites in ``src/agent.py`` were
flipped from sync to ``await`` as part of this migration.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from config.paths import get_data_file
from config.storage_mode import (
    db_writes_enabled,
    file_writes_enabled,
    get_storage_mode,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


class SessionOwnershipService:
    """Tracks which user owns which session."""

    def __init__(self, session_factory: Optional[Callable] = None):
        self.ownership_file = get_data_file("session_ownership.json")
        os.makedirs(os.path.dirname(self.ownership_file), exist_ok=True)
        self._session_factory = session_factory
        # JSON cache — eagerly loaded so `files` and `hybrid` modes
        # behave like the legacy implementation.
        self.ownership_data: Dict[str, Dict[str, Any]] = (
            self._load_ownership_data()
        )

    # ------------------------------------------------------------------
    # JSON helpers (legacy + hybrid fallback)
    # ------------------------------------------------------------------

    def _load_ownership_data(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.ownership_file):
            try:
                with open(self.ownership_file, "r") as f:
                    return json.load(f)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error loading session ownership data: {exc}")
                return {}
        return {}

    def _save_ownership_data(self) -> None:
        try:
            with open(self.ownership_file, "w") as f:
                json.dump(self.ownership_data, f, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error saving session ownership data: {exc}")

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def claim_session(self, user_id: str, session_id: str) -> None:
        if file_writes_enabled():
            now = datetime.utcnow().isoformat()
            if session_id not in self.ownership_data:
                self.ownership_data[session_id] = {
                    "user_id": user_id,
                    "created_at": now,
                    "last_accessed": now,
                }
            else:
                self.ownership_data[session_id]["last_accessed"] = now
            self._save_ownership_data()

        if db_writes_enabled():
            await self._db_claim(user_id, session_id)

    async def get_session_owner(self, session_id: str) -> Optional[str]:
        mode = get_storage_mode()
        if mode != "files":
            owner = await self._db_get_owner(session_id)
            if owner is not None:
                return owner
            if mode == "db":
                return None
        # files or hybrid-with-no-db-row → fall back to JSON
        data = self.ownership_data.get(session_id)
        return data.get("user_id") if data else None

    async def get_user_sessions(self, user_id: str) -> List[str]:
        mode = get_storage_mode()
        if mode != "files":
            db_sessions = await self._db_list_for_user(user_id)
            if mode == "db":
                return db_sessions
            # hybrid: union with JSON-only entries
            json_sessions = [
                sid
                for sid, data in self.ownership_data.items()
                if data.get("user_id") == user_id
            ]
            return list(dict.fromkeys(db_sessions + json_sessions))
        # files mode
        return [
            sid
            for sid, data in self.ownership_data.items()
            if data.get("user_id") == user_id
        ]

    async def is_session_owned_by_user(
        self, session_id: str, user_id: str
    ) -> bool:
        return (await self.get_session_owner(session_id)) == user_id

    async def filter_sessions_for_user(
        self, session_ids: List[str], user_id: str
    ) -> List[str]:
        owned = set(await self.get_user_sessions(user_id))
        return [sid for sid in session_ids if sid in owned]

    async def release_session(self, user_id: str, session_id: str) -> bool:
        released = False

        if file_writes_enabled() and session_id in self.ownership_data:
            if self.ownership_data[session_id].get("user_id") == user_id:
                del self.ownership_data[session_id]
                self._save_ownership_data()
                released = True
            else:
                logger.warning(
                    f"User {user_id} tried to release session "
                    f"{session_id} they don't own (json)"
                )

        if db_writes_enabled():
            db_released = await self._db_release(session_id, user_id)
            released = released or db_released

        return released

    async def get_ownership_stats(self) -> Dict[str, Any]:
        mode = get_storage_mode()
        if mode == "files":
            users = {
                d.get("user_id")
                for d in self.ownership_data.values()
                if d.get("user_id")
            }
            return {
                "total_tracked_sessions": len(self.ownership_data),
                "unique_users": len(users),
                "sessions_per_user": {
                    u: len([s for s, d in self.ownership_data.items() if d.get("user_id") == u])
                    for u in users
                },
            }
        # db / hybrid — best-effort summary from DB only
        try:
            from db.models import SessionOwnership
            from sqlalchemy import select

            sess_factory = self._resolve_session_factory()
            if sess_factory is None:
                return {"total_tracked_sessions": 0, "unique_users": 0}
            async with sess_factory() as session:
                result = await session.execute(select(SessionOwnership))
                rows = result.scalars().all()
            users: Dict[str, int] = {}
            for r in rows:
                users[r.user_id] = users.get(r.user_id, 0) + 1
            return {
                "total_tracked_sessions": len(rows),
                "unique_users": len(users),
                "sessions_per_user": users,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("ownership stats DB read failed", error=str(exc))
            return {"total_tracked_sessions": 0, "unique_users": 0}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_session_factory(self):
        if self._session_factory is not None:
            return self._session_factory
        # Lazy: try the module-level SessionLocal
        try:
            from db.engine import SessionLocal
            return SessionLocal
        except Exception:  # noqa: BLE001
            return None

    async def _db_claim(self, user_id: str, session_id: str) -> None:
        from db.repositories import SessionOwnershipRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return
        try:
            async with sess_factory() as session:
                await SessionOwnershipRepo(session).claim(session_id, user_id)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("DB claim_session failed", error=str(exc))

    async def _db_get_owner(self, session_id: str) -> Optional[str]:
        from db.repositories import SessionOwnershipRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return None
        try:
            async with sess_factory() as session:
                row = await SessionOwnershipRepo(session).get(session_id)
                return row.user_id if row else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("DB get_session_owner failed", error=str(exc))
            return None

    async def _db_list_for_user(self, user_id: str) -> List[str]:
        from db.repositories import SessionOwnershipRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return []
        try:
            async with sess_factory() as session:
                return await SessionOwnershipRepo(session).list_for_user(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DB list_for_user failed", error=str(exc))
            return []

    async def _db_release(self, session_id: str, user_id: str) -> bool:
        from db.repositories import SessionOwnershipRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            return False
        try:
            async with sess_factory() as session:
                ok = await SessionOwnershipRepo(session).release(session_id, user_id)
                await session.commit()
                return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("DB release_session failed", error=str(exc))
            return False


# Global instance — session_factory plumbed in main.py at startup.
session_ownership_service = SessionOwnershipService()
