"""Unit tests for TaskService.dismiss_files."""

from unittest.mock import Mock

import pytest

from models.tasks import FileTask, TaskStatus, UploadTask
from services.task_service import TaskService


@pytest.fixture
def task_service():
    return TaskService(document_service=Mock(), ingestion_timeout=2)


def _failed_file(file_path: str, filename: str) -> FileTask:
    ft = FileTask(file_path=file_path, filename=filename)
    ft.status = TaskStatus.FAILED
    ft.error = "boom"
    return ft


def _store_task(task_service: TaskService, user_id: str, upload_task: UploadTask) -> None:
    task_service.task_store.setdefault(user_id, {})[upload_task.task_id] = upload_task


@pytest.mark.asyncio
async def test_dismiss_removes_failed_file_and_drops_empty_task(task_service):
    ft = _failed_file("/data/a.pdf", "a.pdf")
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/data/a.pdf": ft},
        status=TaskStatus.FAILED,
        failed_files=1,
        processed_files=1,
    )
    _store_task(task_service, "user1", task)

    result = await task_service.dismiss_files("user1", "task-1", file_paths=["/data/a.pdf"])

    assert result["dismissed"] == 1
    assert result["status"] == "accepted"
    assert result["skipped"] == []
    # The task had a single file, so the whole record is dropped.
    assert "task-1" not in task_service.task_store.get("user1", {})


@pytest.mark.asyncio
async def test_dismiss_keeps_task_with_remaining_files_and_adjusts_counters(task_service):
    ft_a = _failed_file("/data/a.pdf", "a.pdf")
    ft_b = _failed_file("/data/b.pdf", "b.pdf")
    task = UploadTask(
        task_id="task-2",
        total_files=2,
        file_tasks={"/data/a.pdf": ft_a, "/data/b.pdf": ft_b},
        status=TaskStatus.FAILED,
        failed_files=2,
        processed_files=2,
    )
    _store_task(task_service, "user1", task)

    result = await task_service.dismiss_files("user1", "task-2", file_paths=["/data/a.pdf"])

    assert result["dismissed"] == 1
    remaining = task_service.task_store["user1"]["task-2"]
    assert set(remaining.file_tasks.keys()) == {"/data/b.pdf"}
    assert remaining.total_files == 1
    assert remaining.failed_files == 1
    assert remaining.processed_files == 1


@pytest.mark.asyncio
async def test_dismiss_skips_non_failed_and_unknown_files(task_service):
    running = FileTask(file_path="/data/live.pdf", filename="live.pdf")
    running.status = TaskStatus.RUNNING
    task = UploadTask(
        task_id="task-3",
        total_files=1,
        file_tasks={"/data/live.pdf": running},
        status=TaskStatus.RUNNING,
    )
    _store_task(task_service, "user1", task)

    result = await task_service.dismiss_files(
        "user1", "task-3", file_paths=["/data/live.pdf", "/data/ghost.pdf"]
    )

    assert result["dismissed"] == 0
    assert result["status"] == "no_op"
    reasons = {entry["reason"] for entry in result["skipped"]}
    assert reasons == {"not_failed", "file_not_in_task"}
    # Nothing removed; the task and its file survive.
    assert "/data/live.pdf" in task_service.task_store["user1"]["task-3"].file_tasks


@pytest.mark.asyncio
async def test_dismiss_returns_none_for_unknown_task(task_service):
    result = await task_service.dismiss_files("user1", "nope", file_paths=["/data/a.pdf"])
    assert result is None
