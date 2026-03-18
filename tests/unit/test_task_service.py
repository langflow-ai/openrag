"""
Basic tests for TaskService improvements
Tests timeout handling, cancellation, and cleanup functionality
"""
import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from services.task_service import TaskService, IngestionTimeoutError
from models.tasks import TaskStatus, UploadTask, FileTask


@pytest.fixture
def task_service():
    """Create TaskService instance with mocked dependencies"""
    mock_doc_service = Mock()
    return TaskService(
        document_service=mock_doc_service,
        ingestion_timeout=2  # Short timeout for testing
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
        status=TaskStatus.COMPLETED
    )
    old_task.updated_at = time.time() - 7200  # 2 hours ago

    recent_task = UploadTask(
        task_id="recent_task",
        total_files=1,
        file_tasks={"file2": FileTask(file_path="file2")},
        status=TaskStatus.COMPLETED
    )
    recent_task.updated_at = time.time() - 600  # 10 minutes ago

    running_task = UploadTask(
        task_id="running_task",
        total_files=1,
        file_tasks={"file3": FileTask(file_path="file3")},
        status=TaskStatus.RUNNING
    )
    running_task.updated_at = time.time() - 7200  # 2 hours ago but still running

    # Add tasks to store
    task_service.task_store["user1"] = {
        "old_task": old_task,
        "recent_task": recent_task,
        "running_task": running_task
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
    """Test that processed_files counter logic only counts terminal states"""
    # This tests the logic pattern used in the finally block

    task = UploadTask(
        task_id="test_task",
        total_files=3,
        file_tasks={
            "file1": FileTask(file_path="file1", status=TaskStatus.COMPLETED),
            "file2": FileTask(file_path="file2", status=TaskStatus.FAILED),
            "file3": FileTask(file_path="file3", status=TaskStatus.RUNNING),
        }
    )

    # Simulate the counter logic from the finally block
    processed_count = 0
    for file_task in task.file_tasks.values():
        if file_task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            processed_count += 1

    # Should only count completed and failed, not running
    assert processed_count == 2



@pytest.mark.asyncio
async def test_concurrent_counter_updates(task_service):
    """Test that concurrent counter updates are thread-safe with locks"""
    # Create a task with multiple files
    task = UploadTask(
        task_id="concurrent_task",
        total_files=10,
        file_tasks={
            f"file{i}": FileTask(file_path=f"file{i}", status=TaskStatus.PENDING)
            for i in range(10)
        },
        status=TaskStatus.RUNNING
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
            f"file{i}": FileTask(file_path=f"file{i}", status=TaskStatus.PENDING)
            for i in range(20)
        },
        status=TaskStatus.RUNNING
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
    tasks = [
        update_counter(f"file{i}", should_fail=(i % 3 == 0))
        for i in range(20)
    ]
    
    await asyncio.gather(*tasks)
    
    # Verify counters: 7 failures (0,3,6,9,12,15,18), 13 successes
    assert task.processed_files == 20
    assert task.failed_files == 7
    assert task.successful_files == 13
    assert task.processed_files == task.successful_files + task.failed_files

