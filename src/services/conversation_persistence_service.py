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
import errno
import json
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from config.paths import get_data_file
from config.storage_mode import (
    db_writes_enabled,
    file_writes_enabled,
    get_storage_mode,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


class PostReplaceSyncError(OSError):
    """The store file was replaced, but the directory fsync then failed.

    The new contents are in place; only their durability across a crash is
    unknown. Callers must not roll back in-memory state for this error.
    """


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
        # Serialises whole saves (snapshot -> write -> replace) so an older
        # snapshot can never replace a newer one. Kept separate from ``lock``
        # so mutators are not blocked during file I/O.
        self._save_lock = threading.Lock()
        # Serialises the JSON-store mutations that prune can roll back (prune,
        # explicit delete, clear), so a failed prune can never resurrect an
        # entry that was deleted while its save was in flight.
        self._file_mutation_lock = asyncio.Lock()
        self._session_factory = session_factory
        self._conversations: dict[str, dict[str, Any]] = self._load_conversations()

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    def _load_conversations(self) -> dict[str, dict[str, Any]]:
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error loading conversations: {exc}")
                return {}
        return {}

    def _save_conversations_sync(self) -> None:
        """Write to a temp file then atomically replace storage_file.

        Takes a shallow snapshot of ``_conversations`` under ``self.lock``
        so the lock is not held during the (potentially slow) file I/O.
        This ensures a failed write (disk full, serialisation error, etc.)
        leaves the existing store intact rather than truncating it.
        """
        with self._save_lock:
            with self.lock:
                snapshot = {uid: dict(convs) for uid, convs in self._conversations.items()}

            dir_ = os.path.dirname(self.storage_file)
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.storage_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            try:
                self._fsync_dir(dir_)
            except OSError as exc:
                raise PostReplaceSyncError(exc.errno, str(exc)) from exc

    @staticmethod
    def _fsync_dir(path: str) -> None:
        """Make the rename durable. Only "unsupported" errors are ignored."""
        unsupported = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
        try:
            dir_fd = os.open(path, os.O_RDONLY)
        except OSError as exc:
            # Platforms that cannot open a directory (e.g. Windows) cannot fsync it.
            if exc.errno in unsupported or isinstance(exc, PermissionError):
                return
            raise
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
        finally:
            os.close(dir_fd)

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
        conversation_state: dict[str, Any],
    ) -> None:
        serialized = self._serialize_datetime(conversation_state)

        if file_writes_enabled():
            with self.lock:
                if user_id not in self._conversations:
                    self._conversations[user_id] = {}
                self._conversations[user_id][response_id] = serialized
            try:
                await self._save_conversations()  # snapshots under lock internally
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to persist conversation to disk",
                    user_id=user_id,
                    response_id=response_id,
                    error=str(exc),
                )
                # Save failure is observable via log; do not block the DB write.

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
        """Delete one conversation from every active store.

        A file-save failure does not skip the DB delete, but it is not hidden:
        the DB delete runs first, then the save error is re-raised so the
        caller knows the JSON copy may survive a restart (and, in hybrid mode,
        be served by the JSON fallback). The entry is already gone from memory;
        the next successful save rewrites the file without it.
        """
        deleted = False
        save_error: Exception | None = None

        if file_writes_enabled():
            # Waits for an in-flight prune, so its rollback cannot undo this.
            async with self._file_mutation_lock:
                with self.lock:
                    user_convs = self._conversations.get(user_id)
                    removed = (
                        user_convs is not None and user_convs.pop(response_id, None) is not None
                    )
                if removed:
                    deleted = True
                    try:
                        await self._save_conversations()
                    except Exception as exc:  # noqa: BLE001
                        save_error = exc
                        logger.error(
                            "Failed to persist conversation deletion to disk",
                            user_id=user_id,
                            response_id=response_id,
                            error=str(exc),
                        )

        if db_writes_enabled():
            db_deleted = await self._db_delete(response_id, user_id)
            deleted = deleted or db_deleted

        if save_error is not None:
            raise save_error
        return deleted

    async def prune_stale_conversations(self, ttl_days: int) -> int:
        """Delete conversations that have had no activity for *ttl_days* days.

        Covers all active storage modes:
        - ``db`` / ``hybrid``: bulk DELETE via the DB repo.
        - ``files`` / ``hybrid``: removes matching entries from the in-memory
          JSON store and persists to disk.

        The JSON-store part is serialised with ``delete_conversation_thread`` and
        ``clear_user_conversations``: if its save fails and entries are rolled
        back, a delete issued meanwhile waits and then removes the restored
        entry, so a deleted conversation is never resurrected.

        Returns the total number of conversations deleted across all stores.
        Raises ``ValueError`` unless *ttl_days* >= 1, before touching memory,
        disk or the DB: zero would delete nearly every conversation and a
        negative value would move the cutoff into the future.
        """
        if ttl_days < 1:
            raise ValueError(f"ttl_days must be at least 1, got {ttl_days}")

        deleted = 0
        # Use local naive time to match the naive timestamps produced by
        # datetime.now() in agent.py.  Each aware timestamp is individually
        # converted to local naive time via astimezone() so Python picks the
        # correct local UTC offset for that instant rather than relying on a
        # single cached tzinfo object.
        cutoff_local = datetime.now() - timedelta(days=ttl_days)

        if file_writes_enabled():
            async with self._file_mutation_lock:
                deleted += await self._prune_file_store(cutoff_local)

        if db_writes_enabled():
            from db.repositories import ConversationRepo

            sess_factory = self._resolve_session_factory()
            if sess_factory is not None:
                try:
                    async with sess_factory() as session:
                        n = await ConversationRepo(session).delete_stale(ttl_days)
                        await session.commit()
                        deleted += n
                except Exception as exc:  # noqa: BLE001
                    logger.error("DB prune_stale_conversations failed", error=str(exc))

        logger.info("Conversation pruning completed", ttl_days=ttl_days, deleted=deleted)
        return deleted

    async def _prune_file_store(self, cutoff_local: datetime) -> int:
        """Drop entries older than *cutoff_local* from the JSON store.

        Returns how many were pruned (0 if the save failed and the entries were
        rolled back). The caller holds ``_file_mutation_lock``, so no explicit
        delete or clear can interleave with the rollback.
        """
        stale_keys: list[tuple[str, str]] = []
        snapshot: dict[tuple[str, str], Any] = {}
        with self.lock:
            for user_id, user_convs in self._conversations.items():
                for resp_id, payload in user_convs.items():
                    last_activity_raw = payload.get("last_activity")
                    if last_activity_raw:
                        try:
                            la = datetime.fromisoformat(str(last_activity_raw))
                            # Aware timestamps: convert to local naive per-timestamp.
                            # Naive timestamps: already local (written by agent.py).
                            if la.tzinfo is not None:
                                la = la.astimezone().replace(tzinfo=None)
                            if la < cutoff_local:
                                stale_keys.append((user_id, resp_id))
                        except (TypeError, ValueError):
                            pass

            if stale_keys:
                # Snapshot payloads before deletion so we can restore on save failure.
                snapshot = {(uid, rid): self._conversations[uid][rid] for uid, rid in stale_keys}
                for user_id, resp_id in stale_keys:
                    del self._conversations[user_id][resp_id]

        if not stale_keys:
            return 0

        try:
            await self._save_conversations()
        except PostReplaceSyncError as exc:
            # The pruned file is already in place; only its durability is in
            # doubt, so memory must keep matching it. Do not roll back.
            logger.error("Pruned conversation store replaced but not fsynced", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to persist conversation pruning to disk", error=str(exc))
            # Restore deleted entries so in-memory state stays consistent
            # with what is on disk — they were not actually pruned.
            # setdefault: an entry stored again while the save was in flight
            # is newer than our snapshot and must win. Explicit deletes cannot
            # interleave here: they wait on _file_mutation_lock.
            with self.lock:
                for (user_id, resp_id), payload in snapshot.items():
                    self._conversations.setdefault(user_id, {}).setdefault(resp_id, payload)
            return 0
        return len(stale_keys)

    async def clear_user_conversations(self, user_id: str) -> None:
        """Delete every conversation for *user_id* from every active store.

        A file-save failure does not skip the DB delete; the error is re-raised
        afterwards, like ``delete_conversation_thread``.
        """
        save_error: Exception | None = None
        if file_writes_enabled():
            # Waits for an in-flight prune, so its rollback cannot undo this.
            async with self._file_mutation_lock:
                with self.lock:
                    removed = self._conversations.pop(user_id, None) is not None
                if removed:
                    try:
                        await self._save_conversations()
                    except Exception as exc:  # noqa: BLE001
                        save_error = exc
                        logger.error(
                            "Failed to persist user conversation clear to disk",
                            user_id=user_id,
                            error=str(exc),
                        )

        if db_writes_enabled():
            await self._db_delete_all(user_id)

        if save_error is not None:
            raise save_error

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
            from sqlalchemy import func, select
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
                    await session.execute(select(func.count(func.distinct(Conversation.user_id))))
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
