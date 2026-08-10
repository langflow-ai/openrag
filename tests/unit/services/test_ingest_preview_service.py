"""Tests for preview-mode Docling cache and index proof helpers."""

import time
from unittest.mock import AsyncMock

import pytest

from models.tasks import FileTask, IngestionPhase, TaskStatus, UploadTask
from services.ingest_preview_service import (
    MAX_PREVIEWS_PER_TASK,
    IngestPreviewService,
    _chunk_sequence,
    _extract_hit_total,
    _sort_hits,
    summarize_docling_document,
)


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
    service = IngestPreviewService(ttl_seconds=300)
    doc = {"pages": [{"page_no": 1}], "texts": [], "tables": [], "pictures": []}

    for i in range(MAX_PREVIEWS_PER_TASK + 5):
        service.store_docling_preview(
            "user-1", "task-1", doc, file_path=f"/tmp/file-{i}.pdf", document_id=f"hash-{i}"
        )

    stored = [k for k in service._entries if k[0] == "user-1" and k[1] == "task-1"]
    assert len(stored) == MAX_PREVIEWS_PER_TASK


def test_chunk_sequence_parses_numeric_suffix():
    assert _chunk_sequence("hash-abc_10") == 10
    assert _chunk_sequence("hash-abc_2") == 2
    assert _chunk_sequence("bad-id") == 0


def test_sort_hits_orders_by_page_then_chunk_sequence():
    hits = [
        {"_id": "doc_10", "_source": {"page": 1}},
        {"_id": "doc_2", "_source": {"page": 1}},
        {"_id": "doc_0", "_source": {"page": 2}},
    ]
    sorted_hits = _sort_hits(hits)
    assert [hit["_id"] for hit in sorted_hits] == ["doc_2", "doc_10", "doc_0"]


def test_extract_hit_total_prefers_total_value():
    assert _extract_hit_total({"total": {"value": 42}, "hits": []}, 0) == 42
    assert _extract_hit_total({"total": 7, "hits": []}, 0) == 7
    assert _extract_hit_total({"hits": []}, 3) == 3


def test_extract_hit_total_falls_back_when_value_is_null():
    # OpenSearch may return {"total": {"value": null}}; must not raise TypeError.
    assert _extract_hit_total({"total": {"value": None}, "hits": []}, 5) == 5


@pytest.mark.asyncio
async def test_get_index_proof_selects_file_by_path():
    service = IngestPreviewService()

    file_a = FileTask(file_path="/tmp/a.pdf", filename="a.pdf")
    file_a.phase = IngestionPhase.LANGFLOW
    file_b = FileTask(file_path="/tmp/b.pdf", filename="b.pdf", document_id="hash-b")
    file_b.phase = IngestionPhase.COMPLETE
    file_b.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1",
        total_files=2,
        file_tasks={"/tmp/a.pdf": file_a, "/tmp/b.pdf": file_b},
        preview_mode=True,
    )

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=opensearch_client,
        file_path="/tmp/b.pdf",
    )

    assert proof["phase"] == "complete"
    assert proof["document_id"] == "hash-b"
    searched_body = opensearch_client.search.await_args.kwargs["body"]
    assert searched_body["query"]["term"]["document_id"] == "hash-b"
    assert "_id" not in str(searched_body.get("sort", []))


@pytest.mark.asyncio
async def test_get_index_proof_rejects_non_preview_task():
    service = IngestPreviewService()
    upload_task = UploadTask(
        task_id="task-1",
        total_files=0,
        file_tasks={},
        preview_mode=False,
    )

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=AsyncMock(),
    )

    assert proof["ready"] is False
    assert proof["error"] == "not_preview_task"


@pytest.mark.asyncio
async def test_get_index_proof_not_ready_while_ingesting():
    service = IngestPreviewService()
    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-sample",
    )
    file_task.phase = IngestionPhase.LANGFLOW
    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/tmp/sample.pdf": file_task},
        preview_mode=True,
    )

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=AsyncMock(),
    )

    assert proof["ready"] is False
    assert proof["phase"] == "langflow"
    assert proof["chunk_count"] == 0


@pytest.mark.asyncio
async def test_get_index_proof_returns_chunks_when_indexed():
    service = IngestPreviewService()

    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-abc",
    )
    file_task.phase = IngestionPhase.COMPLETE
    file_task.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/tmp/sample.pdf": file_task},
        preview_mode=True,
    )

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "hash-abc_10",
                    "_source": {
                        "text": "Later chunk",
                        "page": 1,
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1536,
                    },
                },
                {
                    "_id": "hash-abc_2",
                    "_source": {
                        "text": "Earlier chunk",
                        "page": 1,
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimensions": 1536,
                    },
                },
            ],
            "total": {"value": 250},
        }
    }

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=opensearch_client,
    )

    assert proof["ready"] is True
    assert proof["chunk_count"] == 250
    assert proof["chunks_returned"] == 2
    assert proof["chunks_truncated"] is True
    assert proof["embedding_model"] == "text-embedding-3-small"
    assert proof["embedding_dimensions"] == 1536
    assert len(proof["chunks"]) == 2
    assert proof["chunks"][0]["chunk_id"] == "hash-abc_2"
    assert proof["chunks"][1]["chunk_id"] == "hash-abc_10"
    assert proof["chunks"][0]["char_count"] == len("Earlier chunk")


@pytest.mark.asyncio
async def test_get_index_proof_returns_file_not_found_for_unknown_path():
    service = IngestPreviewService()
    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-sample",
    )
    file_task.phase = IngestionPhase.COMPLETE
    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/tmp/sample.pdf": file_task},
        preview_mode=True,
    )

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=AsyncMock(),
        file_path="/tmp/missing.pdf",
    )

    assert proof["ready"] is False
    assert proof["error"] == "file_not_found"


@pytest.mark.asyncio
async def test_get_index_proof_opensearch_unavailable():
    service = IngestPreviewService()
    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-abc",
    )
    file_task.phase = IngestionPhase.COMPLETE
    file_task.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/tmp/sample.pdf": file_task},
        preview_mode=True,
    )

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=None,
    )

    assert proof["ready"] is False
    assert proof["error"] == "opensearch_unavailable"
    assert proof["phase"] == "complete"
    assert proof["chunk_count"] == 0
    assert proof["document_id"] == "hash-abc"


@pytest.mark.asyncio
async def test_get_index_proof_search_failure():
    service = IngestPreviewService()
    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-abc",
    )
    file_task.phase = IngestionPhase.COMPLETE
    file_task.status = TaskStatus.COMPLETED
    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/tmp/sample.pdf": file_task},
        preview_mode=True,
    )

    opensearch_client = AsyncMock()
    opensearch_client.search.side_effect = RuntimeError("opensearch down")

    proof = await service.get_index_proof(
        upload_task=upload_task,
        task_id="task-1",
        opensearch_client=opensearch_client,
    )

    assert proof["ready"] is False
    assert proof["error"] == "search_failed"
    assert proof["phase"] == "complete"
    assert proof["chunk_count"] == 0
    assert proof["document_id"] == "hash-abc"
