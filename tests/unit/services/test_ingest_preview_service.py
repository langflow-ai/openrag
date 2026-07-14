"""Tests for preview-mode index proof helpers."""

from unittest.mock import AsyncMock

import pytest

from models.tasks import FileTask, IngestionPhase, TaskStatus, UploadTask
from services.ingest_preview_service import (
    IngestPreviewService,
    _chunk_sequence,
    _extract_hit_total,
    _sort_hits,
)


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
