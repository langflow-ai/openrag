"""Tests for preview-mode index proof helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from models.tasks import FileTask, IngestionPhase, TaskStatus, UploadTask
from services.ingest_preview_service import IngestPreviewService


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
    service = IngestPreviewService()
    task_service = MagicMock()
    file_task = FileTask(
        file_path="/tmp/sample.pdf",
        filename="sample.pdf",
        document_id="hash-sample",
    )
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
