"""Index proof helpers and ephemeral Docling parse preview cache."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache

from config.settings import get_index_name
from models.tasks import IngestionPhase
from utils.logging_config import get_logger

logger = get_logger(__name__)

TEXT_PREVIEW_MAX_LENGTH = 240
INDEX_PROOF_MAX_CHUNKS = 200

# Cap how many per-file previews we retain for a single upload task. Preview
# documents can embed full-page rasters, so an unbounded folder/connector sync
# could otherwise grow the in-memory cache without limit. Previews beyond this
# count are simply not cached (the UI falls back to the local/expired state).
MAX_PREVIEWS_PER_TASK = 50

# Global bound for the in-memory Docling preview cache (TTL + maxsize).
MAX_PREVIEW_CACHE_ENTRIES = 500


def summarize_docling_document(document: dict[str, Any]) -> dict[str, int]:
    """Return layout element counts for a DoclingDocument dict."""
    return {
        "page_count": len(document.get("pages") or []),
        "text_count": len(document.get("texts") or []),
        "table_count": len(document.get("tables") or []),
        "picture_count": len(document.get("pictures") or []),
    }


def _chunk_sequence(chunk_id: str | None) -> int:
    """Numeric suffix from chunk ``_id`` (last underscore-delimited segment)."""
    if not chunk_id:
        return 0
    suffix = chunk_id.rsplit("_", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return 0


def _sort_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        hits,
        key=lambda hit: (
            (hit.get("_source") or {}).get("page") or 0,
            _chunk_sequence(hit.get("_id")),
        ),
    )


def _extract_hit_total(hits_section: dict[str, Any], fallback: int) -> int:
    total = hits_section.get("total")
    if isinstance(total, dict):
        value = total.get("value")
        return int(value) if value is not None else fallback
    if isinstance(total, int):
        return total
    return fallback


@dataclass
class _PreviewEntry:
    user_id: str
    file_path: str | None
    document: dict[str, Any]
    stats: dict[str, int]
    expires_at: float
    document_id: str | None = None
    filename: str | None = None


class IngestPreviewService:
    """Index-proof queries plus in-memory TTL cache for Docling parse previews.

    Cache entries are keyed per file (``(user_id, task_id, file_path)``) so a
    single preview-mode upload task can hold a parse preview for each of its
    files. ``file_path`` may be ``None`` for legacy single-file callers.
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._ttl_seconds = max(ttl_seconds, 1)
        self._entries: TTLCache[tuple[str, str, str | None], _PreviewEntry] = TTLCache(
            maxsize=MAX_PREVIEW_CACHE_ENTRIES,
            ttl=self._ttl_seconds,
        )
        # Per-task file_path set for O(task) cap checks (not a full-cache scan).
        self._task_keys: dict[tuple[str, str], set[str | None]] = {}

    def _prune_task_keys(self, user_id: str, task_id: str) -> set[str | None]:
        """Drop file paths whose cache entries already expired or were evicted."""
        task_key = (user_id, task_id)
        known = self._task_keys.get(task_key)
        if not known:
            return set()
        alive = {file_path for file_path in known if (user_id, task_id, file_path) in self._entries}
        if alive:
            self._task_keys[task_key] = alive
        else:
            self._task_keys.pop(task_key, None)
        return alive

    def store_docling_preview(
        self,
        user_id: str,
        task_id: str,
        document: dict[str, Any],
        *,
        file_path: str | None = None,
        document_id: str | None = None,
        filename: str | None = None,
    ) -> None:
        key = (user_id, task_id, file_path)
        task_key = (user_id, task_id)
        alive = self._prune_task_keys(user_id, task_id)
        if key not in self._entries and len(alive) >= MAX_PREVIEWS_PER_TASK:
            logger.debug(
                "Skipping ingest parse preview cache (per-task cap reached)",
                user_id=user_id,
                task_id=task_id,
                file_path=file_path,
                cap=MAX_PREVIEWS_PER_TASK,
            )
            return
        stats = summarize_docling_document(document)
        self._entries[key] = _PreviewEntry(
            user_id=user_id,
            file_path=file_path,
            filename=filename,
            document=document,
            stats=stats,
            expires_at=time.time() + self._ttl_seconds,
            document_id=document_id,
        )
        alive.add(file_path)
        self._task_keys[task_key] = alive
        logger.info(
            "Stored ingest parse preview",
            user_id=user_id,
            task_id=task_id,
            file_path=file_path,
            page_count=stats["page_count"],
            text_count=stats["text_count"],
            table_count=stats["table_count"],
        )

    def get_docling_preview(
        self,
        user_id: str,
        task_id: str,
        file_path: str | None = None,
    ) -> dict[str, Any] | None:
        if file_path is not None:
            entry = self._entries.get((user_id, task_id, file_path))
        else:
            entry = None
            for known_path in self._prune_task_keys(user_id, task_id):
                entry = self._entries.get((user_id, task_id, known_path))
                if entry is not None:
                    break
        if entry is None:
            return None
        return {
            "document": entry.document,
            "stats": entry.stats,
            "expires_at": entry.expires_at,
            "document_id": entry.document_id,
            "file_path": entry.file_path,
            "filename": entry.filename,
        }

    async def get_index_proof(
        self,
        *,
        upload_task: Any,
        task_id: str,
        opensearch_client: Any,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        if not getattr(upload_task, "preview_mode", False):
            return {
                "ready": False,
                "error": "not_preview_task",
                "phase": IngestionPhase.DOCLING.value,
                "chunk_count": 0,
                "chunks": [],
                "chunks_returned": 0,
                "chunks_truncated": False,
                "document_id": None,
            }

        if file_path is not None:
            file_task = upload_task.file_tasks.get(file_path)
            if file_task is None:
                return {
                    "ready": False,
                    "error": "file_not_found",
                    "phase": IngestionPhase.DOCLING.value,
                    "chunk_count": 0,
                    "chunks": [],
                    "chunks_returned": 0,
                    "chunks_truncated": False,
                    "document_id": None,
                }
        else:
            file_task = next(iter(upload_task.file_tasks.values()), None)
        phase = file_task.phase.value if file_task is not None else IngestionPhase.DOCLING.value

        document_id = file_task.document_id if file_task is not None else None

        if file_task is None or file_task.phase != IngestionPhase.COMPLETE:
            return {
                "ready": False,
                "phase": phase,
                "chunk_count": 0,
                "chunks": [],
                "chunks_returned": 0,
                "chunks_truncated": False,
                "document_id": document_id,
            }

        if opensearch_client is None:
            return {
                "ready": False,
                "phase": phase,
                "chunk_count": 0,
                "chunks": [],
                "chunks_returned": 0,
                "chunks_truncated": False,
                "document_id": document_id,
                "error": "opensearch_unavailable",
            }

        try:
            response = await opensearch_client.search(
                index=get_index_name(),
                body={
                    "size": INDEX_PROOF_MAX_CHUNKS,
                    "query": {"term": {"document_id": document_id}},
                    "sort": [{"page": "asc"}],
                    "_source": {
                        "includes": [
                            "text",
                            "page",
                            "embedding_model",
                            "embedding_provider",
                            "embedding_space_id",
                            "embedding_dimensions",
                        ]
                    },
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to query index proof chunks",
                task_id=task_id,
                document_id=document_id,
                error=str(exc),
            )
            return {
                "ready": False,
                "phase": phase,
                "chunk_count": 0,
                "chunks": [],
                "chunks_returned": 0,
                "chunks_truncated": False,
                "document_id": document_id,
                "error": "search_failed",
            }

        hits_section = response.get("hits", {})
        hits = _sort_hits(hits_section.get("hits", []))
        chunk_count = _extract_hit_total(hits_section, len(hits))
        chunks_returned = len(hits)
        chunks_truncated = chunk_count > chunks_returned
        chunks = []
        embedding_model = None
        embedding_provider = None
        embedding_space_id = None
        embedding_dimensions = None

        for hit in hits:
            source = hit.get("_source") or {}
            text = source.get("text") or ""
            if embedding_model is None and source.get("embedding_model"):
                embedding_model = source["embedding_model"]
            if embedding_provider is None and source.get("embedding_provider"):
                embedding_provider = source["embedding_provider"]
            if embedding_space_id is None and source.get("embedding_space_id"):
                embedding_space_id = source["embedding_space_id"]
            if embedding_dimensions is None and source.get("embedding_dimensions"):
                embedding_dimensions = source["embedding_dimensions"]
            preview_text = text.strip()
            if len(preview_text) > TEXT_PREVIEW_MAX_LENGTH:
                preview_text = preview_text[:TEXT_PREVIEW_MAX_LENGTH] + "…"
            chunks.append(
                {
                    "chunk_id": hit.get("_id"),
                    "page": source.get("page"),
                    "text_preview": preview_text,
                    "char_count": len(text),
                }
            )

        return {
            "ready": chunk_count > 0,
            "phase": phase,
            "chunk_count": chunk_count,
            "chunks_returned": chunks_returned,
            "chunks_truncated": chunks_truncated,
            "embedding_model": embedding_model,
            "embedding_provider": embedding_provider,
            "embedding_space_id": embedding_space_id,
            "embedding_dimensions": embedding_dimensions,
            "chunks": chunks,
            "document_id": document_id,
        }
