"""Index proof helpers for preview-mode ingest (no Docling document cache)."""

from __future__ import annotations

from typing import Any

from config.settings import get_index_name
from models.tasks import IngestionPhase
from utils.logging_config import get_logger

logger = get_logger(__name__)

TEXT_PREVIEW_MAX_LENGTH = 240


class IngestPreviewService:
    """Stateless helper for preview-mode index proof queries."""

    async def get_index_proof(
        self,
        *,
        user_id: str,
        task_id: str,
        task_service: Any,
        opensearch_client: Any,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        upload_task = task_service.get_upload_task(user_id, task_id)
        if upload_task is None:
            return {"ready": False, "error": "task_not_found"}

        if file_path is not None:
            file_task = upload_task.file_tasks.get(file_path)
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
                "document_id": document_id,
            }

        if opensearch_client is None:
            return {
                "ready": False,
                "phase": phase,
                "chunk_count": 0,
                "chunks": [],
                "document_id": document_id,
                "error": "opensearch_unavailable",
            }

        try:
            response = await opensearch_client.search(
                index=get_index_name(),
                body={
                    "size": 200,
                    "query": {"term": {"document_id": document_id}},
                    "sort": [{"page": "asc"}, {"_id": "asc"}],
                    "_source": {
                        "includes": [
                            "text",
                            "page",
                            "embedding_model",
                            "embedding_dimensions",
                            "indexed_time",
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
                "document_id": document_id,
                "error": "search_failed",
            }

        hits = response.get("hits", {}).get("hits", [])
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
            "ready": len(chunks) > 0,
            "phase": phase,
            "chunk_count": len(chunks),
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "chunks": chunks,
            "document_id": document_id,
        }
