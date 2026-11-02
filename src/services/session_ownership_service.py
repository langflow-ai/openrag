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

import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

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

    def __init__(self, session_factory: Callable | None = None):
        self.ownership_file = get_data_file("session_ownership.json")
        os.makedirs(os.path.dirname(self.ownership_file), exist_ok=True)
        self._session_factory = session_factory
        # JSON cache — eagerly loaded so `files` and `hybrid` modes
        # behave like the legacy implementation.
        self.ownership_data: dict[str, dict[str, Any]] = self._load_ownership_data()

    # ------------------------------------------------------------------
    # JSON helpers (legacy + hybrid fallback)
    # ------------------------------------------------------------------

    def _load_ownership_data(self) -> dict[str, dict[str, Any]]:
        if os.path.exists(self.ownership_file):
            try:
                with open(self.ownership_file) as f:
                    return json.load(f)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error loading session ownership data: {exc}")
                return {}
        return {}

    def _save_ownership_data(self, data: dict[str, dict[str, Any]]) -> None:
        """Publish a complete file before changing the authorization cache."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=os.path.dirname(self.ownership_file), delete=False
            ) as f:
                temporary = f.name
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.ownership_file)
            self.ownership_data = data
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def claim_session(
        self, user_id: str, session_id: str, conversation_id: str | None = None
    ) -> bool:
        """True only after an owned claim AND its association are persisted.

        Hybrid prefers the DB, with a successfully written JSON file as fallback.
        Ownership conflicts are never treated as backend failures or bypassed.
        An unsuccessful write never adds an authorization entry to the cache.
        """
        canonical_id = conversation_id or session_id
        if file_writes_enabled() and self._file_claim_conflicts(user_id, session_id, canonical_id):
            return False
        durable = False
        if db_writes_enabled():
            try:
                durable = await self._db_claim(user_id, session_id, canonical_id)
            except PermissionError:
                return False
        if file_writes_enabled():
            # Another claim may have published while the DB write was awaiting.
            if self._file_claim_conflicts(user_id, session_id, canonical_id):
                return False
            now = datetime.now(UTC).isoformat()
            existing = self.ownership_data.get(session_id, {})
            if canonical_id != session_id and not durable:
                canonical = self.ownership_data.get(canonical_id)
                if not canonical or canonical.get("user_id") != user_id:
                    return False
            updated = {
                **self.ownership_data,
                session_id: {
                    **existing,
                    "user_id": user_id,
                    "conversation_id": canonical_id,
                    "created_at": existing.get("created_at", now),
                    "last_accessed": now,
                },
            }
            try:
                self._save_ownership_data(updated)
                durable = True
            except Exception as exc:  # noqa: BLE001
                logger.error("File claim_session failed", error=str(exc))
        return durable

    async def get_session_owner(self, session_id: str) -> str | None:
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

    async def get_user_sessions(self, user_id: str) -> list[str]:
        mode = get_storage_mode()
        if mode != "files":
            db_sessions = await self._db_list_for_user(user_id)
            if mode == "db":
                return db_sessions
            # hybrid: union with JSON-only entries
            json_sessions = [
                sid for sid, data in self.ownership_data.items() if data.get("user_id") == user_id
            ]
            return list(dict.fromkeys(db_sessions + json_sessions))
        # files mode
        return [sid for sid, data in self.ownership_data.items() if data.get("user_id") == user_id]

    async def is_session_owned_by_user(self, session_id: str, user_id: str) -> bool:
        return (await self.get_session_owner(session_id)) == user_id

    async def filter_sessions_for_user(self, session_ids: list[str], user_id: str) -> list[str]:
        owned = set(await self.get_user_sessions(user_id))
        return [sid for sid in session_ids if sid in owned]

    async def get_conversation_sessions(self, user_id: str, session_id: str) -> list[str]:
        """Return owned canonical ID first, then aliases, including after restart.

        Deletion must not guess after a DB read failure: otherwise it could leave
        durable aliases authorized while reporting successful removal.
        """
        mode = get_storage_mode()
        files = self.ownership_data if mode != "db" else {}
        data = files.get(session_id, {})
        canonical_id = (
            data.get("conversation_id") or session_id if data.get("user_id") == user_id else None
        )
        sessions = []
        if mode != "files":
            from db.repositories import SessionOwnershipRepo

            factory = self._resolve_session_factory()
            if factory is None and mode == "db":
                raise RuntimeError("Session ownership database unavailable")
            if factory is not None:
                async with factory() as session:
                    repo = SessionOwnershipRepo(session)
                    row = await repo.get(session_id)
                    if row is not None:
                        if row.user_id != user_id:
                            return []
                        canonical_id = row.conversation_id or session_id
                    if canonical_id is None:
                        return []
                    canonical = await repo.get(canonical_id)
                    if canonical is not None:
                        if canonical.user_id != user_id:
                            return []
                    elif files.get(canonical_id, {}).get("user_id") != user_id:
                        return []
                    sessions = await repo.list_for_conversation(canonical_id, user_id)
                    for sid, entry in files.items():
                        if (
                            entry.get("user_id") != user_id
                            or (entry.get("conversation_id") or sid) != canonical_id
                        ):
                            continue
                        authoritative = await repo.get(sid)
                        if authoritative is None or (
                            authoritative.user_id == user_id
                            and (authoritative.conversation_id or sid) == canonical_id
                        ):
                            sessions.append(sid)
                    return list(dict.fromkeys([canonical_id, *sessions]))
        if canonical_id is None or files.get(canonical_id, {}).get("user_id") != user_id:
            return []
        sessions = [
            sid
            for sid, entry in files.items()
            if entry.get("user_id") == user_id
            and (entry.get("conversation_id") or sid) == canonical_id
        ]
        return list(dict.fromkeys([canonical_id, *sessions]))

    async def release_conversation_sessions(self, user_id: str, session_ids: list[str]) -> None:
        """Revoke a complete owned group atomically in each destination.

        The caller must attempt upstream cleanup before revoking associations:
        hybrid groups can contain JSON-only aliases absent from a DB rollback.
        """
        if file_writes_enabled():
            updated = dict(self.ownership_data)
            for session_id in session_ids:
                if updated.get(session_id, {}).get("user_id") == user_id:
                    del updated[session_id]
            self._save_ownership_data(updated)
        if db_writes_enabled():
            from db.repositories import SessionOwnershipRepo

            factory = self._resolve_session_factory()
            if factory is None:
                if get_storage_mode() == "db":
                    raise RuntimeError("Session ownership database unavailable")
                return
            async with factory() as session:
                repo = SessionOwnershipRepo(session)
                for session_id in session_ids:
                    await repo.release(session_id, user_id)
                await session.commit()

    async def release_session(self, user_id: str, session_id: str) -> bool:
        released = False

        if file_writes_enabled() and session_id in self.ownership_data:
            if self.ownership_data[session_id].get("user_id") == user_id:
                updated = dict(self.ownership_data)
                del updated[session_id]
                self._save_ownership_data(updated)
                released = True
            else:
                logger.warning(
                    f"User {user_id} tried to release session {session_id} they don't own (json)"
                )

        if db_writes_enabled():
            db_released = await self._db_release(session_id, user_id)
            released = released or db_released

        return released

    async def get_ownership_stats(self) -> dict[str, Any]:
        mode = get_storage_mode()
        if mode == "files":
            users = {d.get("user_id") for d in self.ownership_data.values() if d.get("user_id")}
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
            from sqlalchemy import select

            from db.models import SessionOwnership

            sess_factory = self._resolve_session_factory()
            if sess_factory is None:
                return {"total_tracked_sessions": 0, "unique_users": 0}
            async with sess_factory() as session:
                result = await session.execute(select(SessionOwnership))
                rows = result.scalars().all()
            user_counts: dict[str, int] = {}
            for r in rows:
                user_counts[r.user_id] = user_counts.get(r.user_id, 0) + 1
            return {
                "total_tracked_sessions": len(rows),
                "unique_users": len(user_counts),
                "sessions_per_user": user_counts,
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

    def _file_claim_conflicts(self, user_id: str, session_id: str, canonical_id: str) -> bool:
        existing = self.ownership_data.get(session_id)
        canonical = self.ownership_data.get(canonical_id)
        return bool(
            existing
            and (
                existing.get("user_id") != user_id
                or (existing.get("conversation_id") or canonical_id) != canonical_id
            )
            or canonical
            and canonical.get("user_id") != user_id
        )

    async def _db_claim(self, user_id: str, session_id: str, conversation_id: str) -> bool:
        from sqlalchemy.exc import IntegrityError

        from db.repositories import SessionOwnershipRepo

        sess_factory = self._resolve_session_factory()
        if sess_factory is None:
            logger.error("DB claim_session failed: database unavailable")
            return False
        try:
            async with sess_factory() as session:
                repo = SessionOwnershipRepo(session)
                canonical = self.ownership_data.get(conversation_id, {})
                if (
                    file_writes_enabled()
                    and conversation_id != session_id
                    and canonical.get("user_id") == user_id
                ):
                    # Reconcile a durable JSON-only canonical claim after DB recovery.
                    await repo.claim(conversation_id, user_id, conversation_id)
                await repo.claim(session_id, user_id, conversation_id)
                await session.commit()
            return True
        except PermissionError:
            raise
        except IntegrityError as exc:
            # A competing insert may now own the ID. Never turn a uniqueness
            # conflict into permission to publish a JSON fallback for this user.
            raise PermissionError("Concurrent session ownership conflict") from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("DB claim_session failed", error=str(exc))
            return False

    async def _db_get_owner(self, session_id: str) -> str | None:
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

    async def _db_list_for_user(self, user_id: str) -> list[str]:
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
            raise RuntimeError("Session ownership database unavailable")
        try:
            async with sess_factory() as session:
                ok = await SessionOwnershipRepo(session).release(session_id, user_id)
                await session.commit()
                return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("DB release_session failed", error=str(exc))
            raise


# Global instance — session_factory plumbed in main.py at startup.
session_ownership_service = SessionOwnershipService()
