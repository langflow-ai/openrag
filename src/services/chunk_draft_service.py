"""Two-slot chunk draft cache for preview-mode customization.

MVP keeps exactly two versions per (user, task, file):
- Docling original: immutable snapshot seeded from the first indexed chunk set
- Last changes: mutable working copy the preview UI edits

OpenSearch is updated only on explicit commit.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from cachetools import TTLCache

from config.settings import get_index_name
from utils.embedding_fields import get_embedding_field_name
from utils.logging_config import get_logger
from utils.opensearch_delete import delete_document_ids

logger = get_logger(__name__)

MAX_DRAFT_CACHE_ENTRIES = 500
TEXT_PREVIEW_MAX_LENGTH = 240
SEED_PAGE_SIZE = 200


@dataclass
class DraftChunk:
    """One chunk in the original or last-changes slot."""

    chunk_id: str  # OpenSearch _id (already ownership-scoped)
    text: str
    page: int | None = None
    vector: list[float] | None = None
    embedding_model: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    dirty: bool = False
    docling_item_refs: list[str] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        preview = self.text.strip()
        if len(preview) > TEXT_PREVIEW_MAX_LENGTH:
            preview = preview[:TEXT_PREVIEW_MAX_LENGTH] + "…"
        return {
            "chunk_id": self.chunk_id,
            "page": self.page,
            "text": self.text,
            "text_preview": preview,
            "char_count": len(self.text),
            "dirty": self.dirty,
            "docling_item_refs": list(self.docling_item_refs),
        }


@dataclass
class ChunkDraftSession:
    user_id: str
    task_id: str
    file_path: str | None
    document_id: str
    original: list[DraftChunk]
    last_changes: list[DraftChunk]
    # What we believe OpenSearch currently holds (updated on successful commit).
    baseline: list[DraftChunk]
    embedding_model: str | None = None
    expires_at: float = 0.0
    # True when last_changes have edits not yet committed to OpenSearch.
    unsaved: bool = False
    chunks_truncated: bool = False
    total_chunks_in_index: int | None = None

    @property
    def dirty(self) -> bool:
        return self.unsaved


def _chunk_from_hit(hit: dict[str, Any]) -> DraftChunk:
    source = dict(hit.get("_source") or {})
    text = source.get("text") or ""
    embedding_model = source.get("embedding_model")
    vector = None
    if embedding_model:
        field_name = get_embedding_field_name(embedding_model)
        raw_vector = source.get(field_name)
        if isinstance(raw_vector, list) and raw_vector:
            vector = list(raw_vector)
    nested = source.get("metadata")
    metadata = dict(nested) if isinstance(nested, dict) else {}
    refs = metadata.get("docling_item_refs")
    docling_item_refs = [str(r) for r in refs] if isinstance(refs, list) else []
    return DraftChunk(
        chunk_id=str(hit.get("_id") or ""),
        text=text,
        page=source.get("page"),
        vector=vector,
        embedding_model=embedding_model,
        source=source,
        metadata=metadata,
        dirty=False,
        docling_item_refs=docling_item_refs,
    )


def _clone_chunks(chunks: list[DraftChunk]) -> list[DraftChunk]:
    return copy.deepcopy(chunks)


def _chunks_fingerprint(chunks: list[DraftChunk]) -> tuple[tuple[str, str, int | None], ...]:
    """Stable identity for comparing draft sets (ids + text + page)."""
    return tuple(
        sorted(
            (c.chunk_id, c.text, c.page)
            for c in chunks
        )
    )


def _extract_hit_total(hits_section: dict[str, Any], fallback: int) -> int:
    total = hits_section.get("total")
    if isinstance(total, dict):
        value = total.get("value")
        return int(value) if value is not None else fallback
    if isinstance(total, int):
        return total
    return fallback


class ChunkDraftService:
    """In-memory Docling-original vs last-changes draft cache."""

    def __init__(self, ttl_seconds: int = 1800):
        self._ttl_seconds = max(ttl_seconds, 1)
        self._sessions: TTLCache[tuple[str, str, str | None], ChunkDraftSession] = TTLCache(
            maxsize=MAX_DRAFT_CACHE_ENTRIES,
            ttl=self._ttl_seconds,
        )

    def _key(
        self, user_id: str, task_id: str, file_path: str | None
    ) -> tuple[str, str, str | None]:
        return (user_id, task_id, file_path)

    def get_session(
        self, user_id: str, task_id: str, file_path: str | None = None
    ) -> ChunkDraftSession | None:
        return self._sessions.get(self._key(user_id, task_id, file_path))

    def clear_session(
        self, user_id: str, task_id: str, file_path: str | None = None
    ) -> None:
        self._sessions.pop(self._key(user_id, task_id, file_path), None)

    async def _load_all_hits(
        self, opensearch_client: Any, document_id: str
    ) -> tuple[list[dict[str, Any]], int]:
        """Scroll all chunks for a document_id; return (hits, total)."""
        index_name = get_index_name()
        response = await opensearch_client.search(
            index=index_name,
            body={
                "size": SEED_PAGE_SIZE,
                "query": {"term": {"document_id": document_id}},
                "sort": [{"page": "asc"}, {"_id": "asc"}],
            },
            scroll="2m",
        )
        scroll_id = response.get("_scroll_id")
        hits_section = response.get("hits") or {}
        hits: list[dict[str, Any]] = list(hits_section.get("hits") or [])
        total = _extract_hit_total(hits_section, len(hits))

        try:
            while True:
                page = hits_section.get("hits") or []
                if len(page) < SEED_PAGE_SIZE or not scroll_id:
                    break
                response = await opensearch_client.scroll(
                    scroll_id=scroll_id, scroll="2m"
                )
                scroll_id = response.get("_scroll_id") or scroll_id
                hits_section = response.get("hits") or {}
                page_hits = hits_section.get("hits") or []
                if not page_hits:
                    break
                hits.extend(page_hits)
        finally:
            if scroll_id and hasattr(opensearch_client, "clear_scroll"):
                try:
                    await opensearch_client.clear_scroll(scroll_id=scroll_id)
                except Exception as exc:
                    logger.debug(
                        "Failed to clear chunk draft seed scroll",
                        error=str(exc),
                    )

        return hits, total

    async def ensure_seeded(
        self,
        *,
        user_id: str,
        task_id: str,
        file_path: str | None,
        document_id: str,
        opensearch_client: Any,
    ) -> ChunkDraftSession:
        existing = self.get_session(user_id, task_id, file_path)
        if existing is not None:
            return existing

        if not document_id:
            raise ValueError("document_id is required to seed chunk draft")
        if opensearch_client is None:
            raise RuntimeError("OpenSearch client unavailable")

        hits, total = await self._load_all_hits(opensearch_client, document_id)
        chunks = [_chunk_from_hit(hit) for hit in hits if hit.get("_id")]
        if not chunks:
            raise ValueError("No indexed chunks available to seed draft")

        truncated = total > len(chunks)
        if truncated:
            logger.warning(
                "Chunk draft seed truncated relative to index total",
                document_id=document_id,
                loaded=len(chunks),
                total=total,
            )

        embedding_model = next(
            (c.embedding_model for c in chunks if c.embedding_model), None
        )
        original = _clone_chunks(chunks)
        session = ChunkDraftSession(
            user_id=user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            original=original,
            last_changes=_clone_chunks(original),
            baseline=_clone_chunks(original),
            embedding_model=embedding_model,
            expires_at=time.time() + self._ttl_seconds,
            chunks_truncated=truncated,
            total_chunks_in_index=total,
        )
        self._sessions[self._key(user_id, task_id, file_path)] = session
        logger.info(
            "Seeded chunk draft session",
            user_id=user_id,
            task_id=task_id,
            file_path=file_path,
            document_id=document_id,
            chunk_count=len(original),
            total_in_index=total,
            truncated=truncated,
        )
        return session

    def session_public(self, session: ChunkDraftSession) -> dict[str, Any]:
        return {
            "document_id": session.document_id,
            "dirty": session.dirty,
            "chunk_count": len(session.last_changes),
            "embedding_model": session.embedding_model,
            "chunks": [c.to_public() for c in session.last_changes],
            "expires_at": session.expires_at,
            "chunks_truncated": session.chunks_truncated,
            "total_chunks_in_index": session.total_chunks_in_index,
        }

    def update_chunk_text(
        self, session: ChunkDraftSession, chunk_id: str, text: str
    ) -> DraftChunk:
        if not text.strip():
            raise ValueError("Chunk text cannot be empty")
        # Preserve user whitespace aside from requiring non-empty content.
        chunk = self._require_last_change(session, chunk_id)
        chunk.text = text
        chunk.dirty = True
        # Text changed — vector is stale until commit re-embeds.
        chunk.vector = None
        session.unsaved = True
        return chunk

    def delete_chunk(self, session: ChunkDraftSession, chunk_id: str) -> None:
        if not any(c.chunk_id == chunk_id for c in session.last_changes):
            raise KeyError(chunk_id)
        if len(session.last_changes) <= 1:
            raise ValueError("Cannot delete the last remaining chunk")
        session.last_changes = [c for c in session.last_changes if c.chunk_id != chunk_id]
        session.unsaved = True

    def revert(self, session: ChunkDraftSession) -> ChunkDraftSession:
        """Reset last-changes to Docling original.

        If OpenSearch was previously committed to a different set, mark unsaved
        so the user can Confirm again to push the original back to the index.
        """
        session.last_changes = _clone_chunks(session.original)
        for chunk in session.last_changes:
            chunk.dirty = False
        session.unsaved = _chunks_fingerprint(session.last_changes) != _chunks_fingerprint(
            session.baseline
        )
        return session

    def _require_last_change(self, session: ChunkDraftSession, chunk_id: str) -> DraftChunk:
        for chunk in session.last_changes:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise KeyError(chunk_id)

    async def commit(
        self,
        session: ChunkDraftSession,
        *,
        opensearch_client: Any,
        write_client: Any,
        embed_texts,
    ) -> dict[str, Any]:
        """Write last-changes to OpenSearch; keep Docling original for the session."""
        if not session.dirty:
            return {"committed": False, "reason": "not_dirty", **self.session_public(session)}

        if write_client is None:
            raise RuntimeError("OpenSearch write client unavailable")

        index_name = get_index_name()
        embedding_model = session.embedding_model
        if not embedding_model:
            raise RuntimeError("Embedding model unknown; cannot commit chunk draft")

        embedding_field = get_embedding_field_name(embedding_model)

        # Capture which chunks changed before we clear dirty flags.
        modified_chunk_ids = [
            chunk.chunk_id
            for chunk in session.last_changes
            if chunk.dirty or not chunk.vector
        ]
        # Only delete ids that were in the seeded original and removed from last_changes.
        # Never delete arbitrary OS ids outside the session (avoids seed-truncation data loss).
        baseline_ids = {c.chunk_id for c in session.baseline}
        original_ids = {c.chunk_id for c in session.original}
        last_ids = {c.chunk_id for c in session.last_changes}
        # Prefer baseline (post-commit OS view) ∪ original for safe removal set.
        known_ids = baseline_ids | original_ids
        removed_chunk_ids = sorted(known_ids - last_ids)

        dirty_texts: list[str] = []
        dirty_indexes: list[int] = []
        for i, chunk in enumerate(session.last_changes):
            needs_embed = chunk.dirty or not chunk.vector
            if needs_embed:
                dirty_indexes.append(i)
                dirty_texts.append(chunk.text)

        if dirty_texts:
            vectors = await embed_texts(embedding_model, dirty_texts)
            if len(vectors) != len(dirty_texts):
                raise RuntimeError("Embedding count mismatch during chunk draft commit")
            for idx, vector in zip(dirty_indexes, vectors, strict=True):
                session.last_changes[idx].vector = list(vector)
                # Keep dirty True until bulk succeeds.

        # Template document fields from first original (or first last-change) source.
        template = None
        if session.original:
            template = dict(session.original[0].source)
        elif session.last_changes:
            template = dict(session.last_changes[0].source)
        if not template:
            raise RuntimeError("No chunk template available for commit")

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bulk_body: list[dict[str, Any]] = []
        for chunk in session.last_changes:
            if not chunk.vector:
                raise RuntimeError(f"Missing vector for chunk {chunk.chunk_id}")
            doc = dict(chunk.source) if chunk.source else dict(template)
            doc["text"] = chunk.text
            doc["page"] = chunk.page if chunk.page is not None else doc.get("page", 0)
            doc["document_id"] = session.document_id
            doc["embedding_model"] = embedding_model
            doc["embedding_dimensions"] = len(chunk.vector)
            doc[embedding_field] = chunk.vector
            doc["indexed_time"] = now_iso
            metadata = dict(chunk.metadata)
            if chunk.docling_item_refs:
                metadata["docling_item_refs"] = list(chunk.docling_item_refs)
            doc["metadata"] = metadata
            chunk.source = doc
            bulk_body.append({"index": {"_index": index_name, "_id": chunk.chunk_id}})
            bulk_body.append(doc)

        if bulk_body:
            result = await write_client.bulk(body=bulk_body, refresh=True)
            if isinstance(result, dict) and result.get("errors"):
                raise RuntimeError(f"OpenSearch bulk commit failed: {result.get('items', [])[:3]}")

        deleted = 0
        if removed_chunk_ids:
            deleted = await delete_document_ids(
                write_client,
                index=index_name,
                document_ids=removed_chunk_ids,
                refresh=True,
            )

        # Only mark clean after successful OS writes.
        for chunk in session.last_changes:
            chunk.dirty = False
        session.baseline = _clone_chunks(session.last_changes)
        session.unsaved = False

        logger.info(
            "Committed chunk draft to OpenSearch",
            task_id=session.task_id,
            document_id=session.document_id,
            chunk_count=len(session.last_changes),
            deleted_removed=deleted,
        )
        filename = template.get("filename") if isinstance(template, dict) else None
        return {
            "committed": True,
            "deleted_stale": deleted,
            "modified_chunk_ids": modified_chunk_ids,
            "removed_chunk_ids": removed_chunk_ids,
            "filename": filename,
            **self.session_public(session),
        }
