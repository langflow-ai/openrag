"""Index proof helpers for preview-mode ingest (no Docling document cache)."""

from __future__ import annotations

from typing import Any

from config.settings import get_index_name
from models.tasks import IngestionPhase
from utils.logging_config import get_logger

logger = get_logger(__name__)

TEXT_PREVIEW_MAX_LENGTH = 240
INDEX_PROOF_MAX_CHUNKS = 200


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


class IngestPreviewService:
    """Stateless helper for preview-mode index proof queries."""

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
        embedding_dimensions = None

        for hit in hits:
            source = hit.get("_source") or {}
            text = source.get("text") or ""
            if embedding_model is None and source.get("embedding_model"):
                embedding_model = source["embedding_model"]
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
            "embedding_dimensions": embedding_dimensions,
            "chunks": chunks,
            "document_id": document_id,
        }
