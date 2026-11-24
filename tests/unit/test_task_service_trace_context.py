"""The task runner tells each file's trace which task and upload session it belongs to."""

from unittest.mock import Mock

import pytest

from models.tasks import FileTask, TaskStatus, UploadTask
from observability.tracing import current_trace_context
from services.task_service import TaskService


@pytest.mark.asyncio
async def test_each_file_is_processed_inside_its_tasks_trace_context():
    seen: list[dict] = []

    class _Processor:
        async def process_item(self, upload_task, item, file_task):
            seen.append(dict(current_trace_context()))
            file_task.status = TaskStatus.COMPLETED

    service = TaskService(document_service=Mock(), ingestion_timeout=2)
    task = UploadTask(
        task_id="task-42",
        total_files=1,
        file_tasks={"/data/a.pdf": FileTask(file_path="/data/a.pdf", filename="a.pdf")},
        processor=_Processor(),
    )
    service.task_store.setdefault("user1", {})["task-42"] = task

    await service.background_custom_processor("user1", "task-42", ["/data/a.pdf"])

    assert seen == [{"session_id": "task-42", "attributes": {"openrag.task_id": "task-42"}}]
    assert current_trace_context() == {}


@pytest.mark.asyncio
async def test_chunk_stats_are_recorded_for_each_processed_file_in_its_trace_context(
    monkeypatch,
):
    recorded: list[tuple] = []

    async def _record(file_task):
        recorded.append((file_task.file_path, file_task.status, dict(current_trace_context())))

    monkeypatch.setattr("services.task_service.record_chunk_stats", _record)

    class _Processor:
        async def process_item(self, upload_task, item, file_task):
            file_task.status = TaskStatus.COMPLETED

    service = TaskService(document_service=Mock(), ingestion_timeout=2)
    task = UploadTask(
        task_id="task-43",
        total_files=1,
        file_tasks={"/data/a.pdf": FileTask(file_path="/data/a.pdf", filename="a.pdf")},
        processor=_Processor(),
    )
    service.task_store.setdefault("user1", {})["task-43"] = task

    await service.background_custom_processor("user1", "task-43", ["/data/a.pdf"])

    assert recorded == [
        (
            "/data/a.pdf",
            TaskStatus.COMPLETED,
            {"session_id": "task-43", "attributes": {"openrag.task_id": "task-43"}},
        )
    ]
