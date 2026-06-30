"""Tests for ephemeral ingest preview cache and index proof helpers."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.tasks import FileTask, IngestionPhase, TaskStatus, UploadTask
from services.ingest_preview_service import IngestPreviewService, summarize_docling_document


def test_summarize_docling_document_counts_layout_elements():
    doc = {
        "pages": [{"page_no": 1}, {"page_no": 2}],
        "texts": [{"text": "Title"}, {"text": "Body"}],
        "tables": [{"data": {}}],
        "pictures": [{"image": {}}],
    }

    stats = summarize_docling_document(doc)

    assert stats == {
        "page_count": 2,
        "text_count": 2,
        "table_count": 1,
        "picture_count": 1,
    }


def test_store_and_get_docling_preview():
    service = IngestPreviewService(ttl_seconds=300)
    doc = {"pages": [{"page_no": 1}], "texts": [], "tables": [], "pictures": []}

    service.store_docling_preview("user-1", "task-1", doc, document_id="hash-abc")

    preview = service.get_docling_preview("user-1", "task-1")
    assert preview is not None
    assert preview["document"] == doc
    assert preview["stats"]["page_count"] == 1
    assert preview["document_id"] == "hash-abc"
    assert preview["expires_at"] > time.time()


def test_store_docling_preview_caps_entries_per_task():
    from services.ingest_preview_service import MAX_PREVIEWS_PER_TASK

    service = IngestPreviewService(ttl_seconds=300)
    doc = {"pages": [{"page_no": 1}], "texts": [], "tables": [], "pictures": []}

    for i in range(MAX_PREVIEWS_PER_TASK + 5):
        service.store_docling_preview(
            "user-1", "task-1", doc, file_path=f"/tmp/file-{i}.pdf", document_id=f"hash-{i}"
        )

    stored = [k for k in service._entries if k[0] == "user-1" and k[1] == "task-1"]
    assert len(stored) == MAX_PREVIEWS_PER_TASK
    # An already-cached file path can still be refreshed past the cap.
    service.store_docling_preview(
        "user-1", "task-1", doc, file_path="/tmp/file-0.pdf", document_id="hash-0-updated"
    )
    refreshed = service.get_docling_preview("user-1", "task-1", file_path="/tmp/file-0.pdf")
    assert refreshed is not None and refreshed["document_id"] == "hash-0-updated"


def test_get_docling_preview_wrong_user_returns_none():
    service = IngestPreviewService(ttl_seconds=300)
    service.store_docling_preview("user-1", "task-1", {"pages": []})

    assert service.get_docling_preview("user-2", "task-1") is None


def test_get_docling_preview_expires_after_ttl():
    service = IngestPreviewService(ttl_seconds=1)
    service.store_docling_preview("user-1", "task-1", {"pages": []})

    entry = service._entries[("user-1", "task-1", None)]
    entry.expires_at = time.time() - 1

    assert service.get_docling_preview("user-1", "task-1") is None
    assert ("user-1", "task-1", None) not in service._entries


def test_store_and_get_docling_preview_per_file():
    service = IngestPreviewService(ttl_seconds=300)
    doc_a = {"pages": [{"page_no": 1}], "texts": [], "tables": [], "pictures": []}
    doc_b = {"pages": [{"page_no": 1}, {"page_no": 2}], "texts": [], "tables": [], "pictures": []}

    service.store_docling_preview(
        "user-1", "task-1", doc_a, file_path="/tmp/a.pdf", document_id="hash-a", filename="a.pdf"
    )
    service.store_docling_preview(
        "user-1", "task-1", doc_b, file_path="/tmp/b.pdf", document_id="hash-b", filename="b.pdf"
    )

    preview_a = service.get_docling_preview("user-1", "task-1", file_path="/tmp/a.pdf")
    preview_b = service.get_docling_preview("user-1", "task-1", file_path="/tmp/b.pdf")

    assert preview_a is not None and preview_a["document_id"] == "hash-a"
    assert preview_a["filename"] == "a.pdf"
    assert preview_b is not None and preview_b["document_id"] == "hash-b"
    assert preview_b["stats"]["page_count"] == 2

    # Lookup without file_path returns one of the task's entries (back-compat).
    assert service.get_docling_preview("user-1", "task-1") is not None


@pytest.mark.asyncio
async def test_get_index_proof_selects_file_by_path():
    service = IngestPreviewService(ttl_seconds=300)
    service.store_docling_preview(
        "user-1", "task-1", {"pages": []}, file_path="/tmp/b.pdf", document_id="hash-b"
    )

    file_a = FileTask(file_path="/tmp/a.pdf", filename="a.pdf")
    file_a.phase = IngestionPhase.LANGFLOW
    file_b = FileTask(file_path="/tmp/b.pdf", filename="b.pdf")
    file_b.phase = IngestionPhase.COMPLETE
    file_b.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1",
        total_files=2,
        file_tasks={"/tmp/a.pdf": file_a, "/tmp/b.pdf": file_b},
    )

    task_service = MagicMock()
    task_service.get_upload_task.return_value = upload_task

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}

    proof = await service.get_index_proof(
        user_id="user-1",
        task_id="task-1",
        task_service=task_service,
        opensearch_client=opensearch_client,
        file_path="/tmp/b.pdf",
    )

    assert proof["phase"] == "complete"
    assert proof["document_id"] == "hash-b"
    searched_body = opensearch_client.search.await_args.kwargs["body"]
    assert searched_body["query"]["term"]["document_id"] == "hash-b"


@pytest.mark.asyncio
async def test_get_index_proof_not_ready_while_ingesting():
    service = IngestPreviewService(ttl_seconds=300)
    task_service = MagicMock()
    file_task = FileTask(file_path="/tmp/sample.pdf", filename="sample.pdf")
    file_task.phase = IngestionPhase.LANGFLOW
    upload_task = UploadTask(
        task_id="task-1", total_files=1, file_tasks={"/tmp/sample.pdf": file_task}
    )
    task_service.get_upload_task.return_value = upload_task

    proof = await service.get_index_proof(
        user_id="user-1",
        task_id="task-1",
        task_service=task_service,
        opensearch_client=AsyncMock(),
    )

    assert proof["ready"] is False
    assert proof["phase"] == "langflow"
    assert proof["chunk_count"] == 0


@pytest.mark.asyncio
async def test_get_index_proof_returns_chunks_when_indexed(monkeypatch):
    service = IngestPreviewService(ttl_seconds=300)
    service.store_docling_preview("user-1", "task-1", {"pages": []}, document_id="hash-abc")

    file_task = FileTask(file_path="/tmp/sample.pdf", filename="sample.pdf")
    file_task.phase = IngestionPhase.COMPLETE
    file_task.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1", total_files=1, file_tasks={"/tmp/sample.pdf": file_task}
    )

    task_service = MagicMock()
    task_service.get_upload_task.return_value = upload_task

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "hash-abc_0",
                    "_source": {
                        "text": "DocLayNet abstract text " * 5,
                        "page": 1,
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1536,
                    },
                },
                {
                    "_id": "hash-abc_1",
                    "_source": {
                        "text": "Table row content",
                        "page": 1,
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1536,
                    },
                },
            ],
            "total": {"value": 2},
        }
    }

    proof = await service.get_index_proof(
        user_id="user-1",
        task_id="task-1",
        task_service=task_service,
        opensearch_client=opensearch_client,
    )

    assert proof["ready"] is True
    assert proof["chunk_count"] == 2
    assert proof["embedding_model"] == "text-embedding-3-small"
    assert proof["embedding_dimensions"] == 1536
    assert len(proof["chunks"]) == 2
    assert proof["chunks"][0]["chunk_id"] == "hash-abc_0"
    assert proof["chunks"][0]["char_count"] == len("DocLayNet abstract text " * 5)
