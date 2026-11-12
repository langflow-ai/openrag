"""TaskService reports each file's final status to a processor's on_file_finished hook.

The ingestion timeout cancels process_item while the file is still RUNNING and
TaskService then sets FAILED itself, so a processor can only learn of that
failure from this hook.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from models.processors import ConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from services.task_service import TaskService

ITEM = "bucket::docs/report.pdf"


class _HookProcessor:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.finished: list[tuple[str, TaskStatus, str | None]] = []

    async def process_item(self, upload_task, item, file_task):
        await self.behaviour(upload_task, item, file_task)

    async def on_file_finished(self, upload_task, item, file_task):
        self.finished.append((item, file_task.status, file_task.error))


async def _run(processor, timeout=2):
    service = TaskService(document_service=Mock(), ingestion_timeout=timeout)
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={ITEM: FileTask(file_path=ITEM, filename="report.pdf")},
        processor=processor,
    )
    service.task_store.setdefault("user1", {})["task-1"] = task
    await service.background_custom_processor("user1", "task-1", [ITEM])
    return task


@pytest.mark.asyncio
async def test_hook_sees_completed_status():
    async def ok(upload_task, item, file_task):
        file_task.status = TaskStatus.COMPLETED

    processor = _HookProcessor(ok)
    await _run(processor)

    assert processor.finished == [(ITEM, TaskStatus.COMPLETED, None)]


@pytest.mark.asyncio
async def test_hook_sees_failure_assigned_by_the_ingestion_timeout():
    async def hangs(upload_task, item, file_task):
        file_task.status = TaskStatus.RUNNING
        await asyncio.sleep(30)

    processor = _HookProcessor(hangs)
    task = await _run(processor, timeout=1)

    assert task.file_tasks[ITEM].status == TaskStatus.FAILED
    assert len(processor.finished) == 1
    _, status, error = processor.finished[0]
    assert status == TaskStatus.FAILED
    assert "timed out" in error


@pytest.mark.asyncio
async def test_hook_sees_failure_from_a_raising_processor():
    async def boom(upload_task, item, file_task):
        raise RuntimeError("converter crashed")

    processor = _HookProcessor(boom)
    await _run(processor)

    assert processor.finished == [(ITEM, TaskStatus.FAILED, "converter crashed")]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["File cancelled by user", "Task cancelled by user"])
async def test_user_cancellations_are_not_reported(message):
    async def cancelled(upload_task, item, file_task):
        file_task.status = TaskStatus.FAILED
        file_task.error = message

    processor = _HookProcessor(cancelled)
    await _run(processor)

    assert processor.finished == []


@pytest.mark.asyncio
async def test_a_failing_hook_does_not_break_the_task():
    async def ok(upload_task, item, file_task):
        file_task.status = TaskStatus.COMPLETED

    processor = _HookProcessor(ok)
    processor.on_file_finished = AsyncMock(side_effect=RuntimeError("db down"))
    task = await _run(processor)

    assert task.file_tasks[ITEM].status == TaskStatus.COMPLETED
    assert task.processed_files == 1


@pytest.mark.asyncio
async def test_processors_without_the_hook_are_unaffected():
    class _Plain:
        async def process_item(self, upload_task, item, file_task):
            file_task.status = TaskStatus.COMPLETED

    task = await _run(_Plain())

    assert task.file_tasks[ITEM].status == TaskStatus.COMPLETED


def _connector_processor():
    processor = object.__new__(ConnectorFileProcessor)
    processor.user_id = "user1"
    processor.connector_type = "aws_s3"
    processor.preview_mode = False
    processor.file_versions = {ITEM: ("etag-1", None)}
    return processor


@pytest.mark.asyncio
async def test_connector_processor_records_a_timeout_failure_in_the_registry():
    processor = _connector_processor()

    async def hangs(upload_task, item, file_task):
        file_task.status = TaskStatus.RUNNING
        await asyncio.sleep(30)

    processor._process_connector_file = hangs

    with patch("services.failed_ingestion_service.record_failure", new=AsyncMock()) as record:
        await _run(processor, timeout=1)

    record.assert_awaited_once()
    args, kwargs = record.await_args
    assert args[:3] == ("user1", "aws_s3", ITEM)
    assert "timed out" in args[3]
    assert kwargs["version"] == ("etag-1", None)


@pytest.mark.asyncio
async def test_connector_processor_clears_the_registry_on_success():
    processor = _connector_processor()

    async def ok(upload_task, item, file_task):
        file_task.status = TaskStatus.COMPLETED

    processor._process_connector_file = ok

    with (
        patch("services.failed_ingestion_service.record_failure", new=AsyncMock()) as record,
        patch("services.failed_ingestion_service.clear_failure", new=AsyncMock()) as clear,
    ):
        await _run(processor)

    record.assert_not_awaited()
    clear.assert_awaited_once_with("user1", "aws_s3", ITEM)


@pytest.mark.asyncio
async def test_connector_processor_does_not_record_a_user_cancellation():
    processor = _connector_processor()

    async def cancelled(upload_task, item, file_task):
        file_task.status = TaskStatus.FAILED
        file_task.error = "File cancelled by user"

    processor._process_connector_file = cancelled

    with patch("services.failed_ingestion_service.record_failure", new=AsyncMock()) as record:
        await _run(processor)

    record.assert_not_awaited()
