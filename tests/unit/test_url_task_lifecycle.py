"""Task lifecycle coverage for URL sources that reserve their task ID first."""

import asyncio
from unittest.mock import Mock

import pytest

from models.processors import TaskProcessor
from services.task_service import TaskService


class _BlockingProcessor(TaskProcessor):
    def __init__(self, started: asyncio.Event):
        super().__init__()
        self.started = started

    async def process_item(self, _upload_task, _item, _file_task) -> None:
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_reserved_task_id_keeps_a_background_task_for_cancellation():
    service = TaskService(document_service=Mock(), ingestion_timeout=5)
    started = asyncio.Event()

    task_id = await service.create_custom_task(
        "user-1",
        ["source-1"],
        _BlockingProcessor(started),
        existing_task_id="reserved-url-task-id",
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    upload_task = service.get_upload_task("user-1", task_id)
    assert upload_task is not None
    assert upload_task.background_task is not None
    assert await service.cancel_task("user-1", task_id) is True
    assert upload_task.background_task.cancelled()
