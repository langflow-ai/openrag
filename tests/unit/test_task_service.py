"""
Basic tests for TaskService improvements
Tests timeout handling, cancellation, and cleanup functionality
"""

import asyncio
import time
from unittest.mock import Mock, patch

import pytest

from models.tasks import FileTask, TaskStatus, UploadTask
from services.task_service import IngestionTimeoutError, TaskService


@pytest.fixture
def task_service():
    """Create TaskService instance with mocked dependencies"""
    mock_doc_service = Mock()
    return TaskService(
        document_service=mock_doc_service,
        ingestion_timeout=2,  # Short timeout for testing
    )


@pytest.mark.asyncio
async def test_process_with_timeout_success(task_service):
    """Test that _process_with_timeout completes successfully within timeout"""

    async def quick_task():
        await asyncio.sleep(0.01)
        return "success"

    result = await task_service._process_with_timeout(quick_task(), timeout_seconds=1)
    assert result == "success"


@pytest.mark.asyncio
async def test_process_with_timeout_exceeds(task_service):
    """Test that _process_with_timeout raises IngestionTimeoutError when timeout is exceeded"""

    async def slow_task():
        await asyncio.sleep(10)
        return "should not reach here"

    with pytest.raises(IngestionTimeoutError) as exc_info:
        await task_service._process_with_timeout(slow_task(), timeout_seconds=0.5)

    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_cleanup_old_tasks(task_service):
    """Test that cleanup_old_tasks removes old completed tasks"""
    # Create some test tasks
    old_task = UploadTask(
        task_id="old_task",
        total_files=1,
        file_tasks={"file1": FileTask(file_path="file1")},
        status=TaskStatus.COMPLETED,
    )
    old_task.updated_at = time.time() - 7200  # 2 hours ago

    recent_task = UploadTask(
        task_id="recent_task",
        total_files=1,
        file_tasks={"file2": FileTask(file_path="file2")},
        status=TaskStatus.COMPLETED,
    )
    recent_task.updated_at = time.time() - 600  # 10 minutes ago

    running_task = UploadTask(
        task_id="running_task",
        total_files=1,
        file_tasks={"file3": FileTask(file_path="file3")},
        status=TaskStatus.RUNNING,
    )
    running_task.updated_at = time.time() - 7200  # 2 hours ago but still running

    # Add tasks to store
    task_service.task_store["user1"] = {
        "old_task": old_task,
        "recent_task": recent_task,
        "running_task": running_task,
    }
    # Pre-create locks for the tasks
    task_service._task_locks["old_task"] = asyncio.Lock()
    task_service._task_locks["recent_task"] = asyncio.Lock()

    # Cleanup tasks older than 1 hour
    cleaned = await task_service.cleanup_old_tasks(max_age_seconds=3600)

    # Should have cleaned up 1 task (old_task)
    assert cleaned == 1
    assert "old_task" not in task_service.task_store["user1"]
    assert "recent_task" in task_service.task_store["user1"]
    assert "running_task" in task_service.task_store["user1"]  # Running tasks not cleaned
    # Verify lock was also cleaned up
    assert "old_task" not in task_service._task_locks
    assert "recent_task" in task_service._task_locks  # Recent task lock should remain


@pytest.mark.asyncio
async def test_cleanup_old_tasks_force_cleans_retained_temp_files(task_service):
    """Evicted tasks must reclaim temps kept for retryable local failures."""
    temp_path = "/var/folders/tmp/retryable.tmp"
    old_task = UploadTask(
        task_id="old_task",
        total_files=1,
        file_tasks={"file1": FileTask(file_path="file1")},
        temp_file_paths=[temp_path],
        status=TaskStatus.FAILED,
    )
    old_task.updated_at = time.time() - 7200

    task_service.task_store["user1"] = {"old_task": old_task}

    with patch.object(task_service, "_cleanup_upload_temp_files") as mock_cleanup:
        cleaned = await task_service.cleanup_old_tasks(max_age_seconds=3600)

    assert cleaned == 1
    mock_cleanup.assert_called_once_with(old_task, force=True)


@pytest.mark.asyncio
async def test_shutdown_force_cleans_upload_temp_files(task_service):
    upload_task = UploadTask(
        task_id="task1",
        total_files=1,
        file_tasks={},
        temp_file_paths=["/var/folders/tmp/retryable.tmp"],
        status=TaskStatus.FAILED,
    )
    task_service.task_store["user1"] = {"task1": upload_task}

    with patch.object(task_service, "_cleanup_upload_temp_files") as mock_cleanup:
        await task_service.shutdown()

    mock_cleanup.assert_called_once_with(upload_task, force=True)


@pytest.mark.asyncio
async def test_shutdown_cancels_background_tasks(task_service):
    """Test that shutdown properly cancels background tasks"""

    async def background_work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    # Add a real background task
    bg_task = asyncio.create_task(background_work())
    task_service.background_tasks.add(bg_task)

    # Give the task a moment to start
    await asyncio.sleep(0.01)

    # Shutdown should cancel it
    await task_service.shutdown()

    # Verify task was actually cancelled (not just done)
    assert bg_task.done()
    assert bg_task.cancelled()


def test_counter_consistency_logic(task_service):
    """Test that processed_files counter logic only counts terminal states.

    SKIPPED must count as terminal — connector sync marks source-deleted
    files SKIPPED, and excluding them caused the upload task to hang
    forever (processed_files never reaching total_files).
    """
    # This tests the logic pattern used in the finally block

    task = UploadTask(
        task_id="test_task",
        total_files=4,
        file_tasks={
            "file1": FileTask(file_path="file1", status=TaskStatus.COMPLETED),
            "file2": FileTask(file_path="file2", status=TaskStatus.FAILED),
            "file3": FileTask(file_path="file3", status=TaskStatus.RUNNING),
            "file4": FileTask(file_path="file4", status=TaskStatus.SKIPPED),
        },
    )

    # Simulate the counter logic from the finally block
    processed_count = 0
    for file_task in task.file_tasks.values():
        if file_task.status in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.SKIPPED,
        ]:
            processed_count += 1

    # Should count completed, failed, and skipped — but not running
    assert processed_count == 3


@pytest.mark.asyncio
async def test_concurrent_counter_updates(task_service):
    """Test that concurrent counter updates are thread-safe with locks"""
    # Create a task with multiple files
    task = UploadTask(
        task_id="concurrent_task",
        total_files=10,
        file_tasks={
            f"file{i}": FileTask(file_path=f"file{i}", status=TaskStatus.PENDING) for i in range(10)
        },
        status=TaskStatus.RUNNING,
    )

    task_service.task_store["user1"] = {"concurrent_task": task}

    # Simulate concurrent updates to counters
    async def update_counter(file_id: str):
        """Simulate processing a file and updating counters"""
        file_task = task.file_tasks[file_id]

        # Simulate some processing time
        await asyncio.sleep(0.01)

        # Update file status
        file_task.status = TaskStatus.COMPLETED

        # Update counters with lock (as done in the actual code)
        async with task_service._get_task_lock("concurrent_task"):
            task.processed_files += 1
            task.successful_files += 1

    # Run all updates concurrently
    await asyncio.gather(*[update_counter(f"file{i}") for i in range(10)])

    # Verify all counters are correct (no race conditions)
    assert task.processed_files == 10
    assert task.successful_files == 10
    assert task.failed_files == 0

    # Verify all file tasks are completed
    for file_task in task.file_tasks.values():
        assert file_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_concurrent_mixed_counter_updates(task_service):
    """Test concurrent updates with mixed success/failure outcomes"""
    task = UploadTask(
        task_id="mixed_task",
        total_files=20,
        file_tasks={
            f"file{i}": FileTask(file_path=f"file{i}", status=TaskStatus.PENDING) for i in range(20)
        },
        status=TaskStatus.RUNNING,
    )

    task_service.task_store["user1"] = {"mixed_task": task}

    async def update_counter(file_id: str, should_fail: bool):
        """Simulate processing with success or failure"""
        file_task = task.file_tasks[file_id]
        await asyncio.sleep(0.01)

        # Update file status and counters atomically
        async with task_service._get_task_lock("mixed_task"):
            if should_fail:
                file_task.status = TaskStatus.FAILED
                task.failed_files += 1
            else:
                file_task.status = TaskStatus.COMPLETED
                task.successful_files += 1
            task.processed_files += 1

    # Create mix of successful and failed tasks
    tasks = [update_counter(f"file{i}", should_fail=(i % 3 == 0)) for i in range(20)]

    await asyncio.gather(*tasks)

    # Verify counters: 7 failures (0,3,6,9,12,15,18), 13 successes
    assert task.processed_files == 20
    assert task.failed_files == 7
    assert task.successful_files == 13
    assert task.processed_files == task.successful_files + task.failed_files


def test_enhanced_drops_completed_files_for_normal_tasks(task_service):
    """Task panel keeps its list tidy: completed files are not surfaced."""
    task = UploadTask(
        task_id="normal_task",
        total_files=2,
        file_tasks={
            "fileA": FileTask(file_path="fileA", status=TaskStatus.COMPLETED),
            "fileB": FileTask(file_path="fileB", status=TaskStatus.RUNNING),
        },
        status=TaskStatus.RUNNING,
    )
    task_service.task_store["user1"] = {"normal_task": task}

    tasks = task_service.get_all_tasks2("user1")

    files = tasks[0]["files"]
    assert "fileA" not in files  # completed dropped
    assert "fileB" in files


def test_enhanced_keeps_completed_files_for_preview_tasks(task_service):
    """Preview tasks must retain completed files so the live preview carousel
    can still enumerate them and render their cached Docling layout."""
    task = UploadTask(
        task_id="preview_task",
        total_files=2,
        file_tasks={
            "fileA": FileTask(file_path="fileA", status=TaskStatus.COMPLETED),
            "fileB": FileTask(file_path="fileB", status=TaskStatus.RUNNING),
        },
        status=TaskStatus.RUNNING,
        preview_mode=True,
    )
    task_service.task_store["user1"] = {"preview_task": task}

    tasks = task_service.get_all_tasks2("user1")

    files = tasks[0]["files"]
    assert "fileA" in files  # completed retained for preview
    assert files["fileA"]["status"] == "completed"
    assert "fileB" in files


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------


def _make_terminal_task(task_id: str, status: TaskStatus) -> UploadTask:
    return UploadTask(
        task_id=task_id,
        total_files=1,
        file_tasks={"f": FileTask(file_path="f", status=status)},
        status=status,
    )


def test_delete_task_returns_deleted_for_completed(task_service):
    task = _make_terminal_task("t1", TaskStatus.COMPLETED)
    task_service.task_store["user1"] = {"t1": task}
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "t1") is TaskDeleteResult.DELETED
    assert "t1" not in task_service.task_store.get("user1", {})


def test_delete_task_returns_deleted_for_failed(task_service):
    task = _make_terminal_task("t2", TaskStatus.FAILED)
    task_service.task_store["user1"] = {"t2": task}
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "t2") is TaskDeleteResult.DELETED
    assert "user1" not in task_service.task_store  # store entry pruned when empty


def test_delete_task_returns_not_found_for_absent_task(task_service):
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "nonexistent") is TaskDeleteResult.NOT_FOUND


def test_delete_task_returns_in_progress_for_running_task(task_service):
    task = _make_terminal_task("t3", TaskStatus.RUNNING)
    task_service.task_store["user1"] = {"t3": task}
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "t3") is TaskDeleteResult.IN_PROGRESS
    assert "t3" in task_service.task_store["user1"]  # must not be removed


def test_delete_task_returns_in_progress_for_pending_task(task_service):
    task = _make_terminal_task("t4", TaskStatus.PENDING)
    task_service.task_store["user1"] = {"t4": task}
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "t4") is TaskDeleteResult.IN_PROGRESS


def test_delete_task_removes_lock(task_service):
    import asyncio

    task = _make_terminal_task("t5", TaskStatus.COMPLETED)
    task_service.task_store["user1"] = {"t5": task}
    task_service._task_locks["t5"] = asyncio.Lock()
    from models.tasks import TaskDeleteResult

    assert task_service.delete_task("user1", "t5") is TaskDeleteResult.DELETED
    assert "t5" not in task_service._task_locks


def test_delete_task_resolves_anonymous_shared_task(task_service):
    """delete_task must find tasks stored under the anonymous key."""
    from models.tasks import TaskDeleteResult
    from session_manager import AnonymousUser

    anon_id = AnonymousUser().user_id
    task = _make_terminal_task("shared1", TaskStatus.COMPLETED)
    task_service.task_store[anon_id] = {"shared1": task}
    assert task_service.delete_task("real_user", "shared1") is TaskDeleteResult.DELETED
    assert "shared1" not in task_service.task_store.get(anon_id, {})


# ---------------------------------------------------------------------------
# delete_all_terminal_tasks
# ---------------------------------------------------------------------------


def test_delete_all_terminal_tasks_removes_only_terminal(task_service):
    completed = _make_terminal_task("c1", TaskStatus.COMPLETED)
    failed = _make_terminal_task("f1", TaskStatus.FAILED)
    running = _make_terminal_task("r1", TaskStatus.RUNNING)
    task_service.task_store["user1"] = {"c1": completed, "f1": failed, "r1": running}

    deleted = task_service.delete_all_terminal_tasks("user1")

    assert set(deleted) == {"c1", "f1"}
    assert "r1" in task_service.task_store["user1"]
    assert "c1" not in task_service.task_store.get("user1", {})
    assert "f1" not in task_service.task_store.get("user1", {})


def test_delete_all_terminal_tasks_returns_empty_for_unknown_user(task_service):
    assert task_service.delete_all_terminal_tasks("nobody") == []


def test_delete_all_terminal_tasks_prunes_empty_user_store(task_service):
    task = _make_terminal_task("c1", TaskStatus.COMPLETED)
    task_service.task_store["user1"] = {"c1": task}
    task_service.delete_all_terminal_tasks("user1")
    assert "user1" not in task_service.task_store


def test_delete_all_terminal_tasks_does_not_touch_anonymous_store(task_service):
    """Bulk clear must not remove shared anonymous tasks — they are visible to
    all authenticated users and are only aged out by cleanup_old_tasks."""
    from session_manager import AnonymousUser

    anon_id = AnonymousUser().user_id
    anon_task = _make_terminal_task("anon1", TaskStatus.COMPLETED)
    own_task = _make_terminal_task("own1", TaskStatus.COMPLETED)
    task_service.task_store[anon_id] = {"anon1": anon_task}
    task_service.task_store["user1"] = {"own1": own_task}

    deleted = task_service.delete_all_terminal_tasks("user1")

    assert deleted == ["own1"]
    # shared anonymous task must still be present
    assert "anon1" in task_service.task_store[anon_id]


def test_delete_all_terminal_tasks_removes_lock(task_service):
    import asyncio

    task = _make_terminal_task("c2", TaskStatus.COMPLETED)
    task_service.task_store["user1"] = {"c2": task}
    task_service._task_locks["c2"] = asyncio.Lock()
    task_service.delete_all_terminal_tasks("user1")
    assert "c2" not in task_service._task_locks
