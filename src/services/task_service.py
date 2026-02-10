import asyncio
import os
import random
import time
import uuid
from typing import Any, Coroutine, TypeVar

from models.tasks import FileTask, TaskStatus, UploadTask
from session_manager import AnonymousUser
from utils.gpu_detection import get_worker_count
from utils.logging_config import get_logger
from utils.telemetry import TelemetryClient, Category, MessageId

T = TypeVar("T")

logger = get_logger(__name__)


class IngestionTimeoutError(Exception):
    """Raised when file processing exceeds the configured timeout"""
    pass


class TaskService:
    # Cleanup interval in seconds (2 hours)
    CLEANUP_INTERVAL_SECONDS = 2 * 60 * 60

    def __init__(self, document_service=None, process_pool=None, ingestion_timeout=3600):
        self.document_service = document_service
        self.process_pool = process_pool
        self.task_store: dict[
            str, dict[str, UploadTask]
        ] = {}  # user_id -> {task_id -> UploadTask}
        self.background_tasks = set()
        self.ingestion_timeout = ingestion_timeout
        self._cleanup_task: asyncio.Task | None = None
        # Locks for task counter updates, keyed by task_id
        # Kept separate from UploadTask to maintain serialization compatibility
        self._task_locks: dict[str, asyncio.Lock] = {}
        # Global semaphore to limit concurrent file processing across all tasks.
        # TaskService is a singleton, so this limits concurrency system-wide.
        self._worker_count = get_worker_count()
        self._processing_semaphore = asyncio.Semaphore(self._worker_count)

        if self.process_pool is None:
            raise ValueError("TaskService requires a process_pool parameter")

    def _get_task_lock(self, task_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific task's counter updates"""
        if task_id not in self._task_locks:
            self._task_locks[task_id] = asyncio.Lock()
        return self._task_locks[task_id]

    def start_cleanup_scheduler(self) -> None:
        """Start the periodic cleanup background task.

        Should be called once after the event loop is running (e.g., during app startup).
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.info(
                "Started periodic task cleanup scheduler",
                interval_seconds=self.CLEANUP_INTERVAL_SECONDS,
            )

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up old completed/failed tasks."""
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
                cleaned = await self.cleanup_old_tasks()
                if cleaned > 0:
                    logger.debug("Periodic cleanup completed", tasks_cleaned=cleaned)
            except asyncio.CancelledError:
                logger.debug("Periodic cleanup task cancelled")
                raise
            except Exception as e:
                logger.warning("Error during periodic cleanup", error=str(e))

    async def exponential_backoff_delay(
        self, retry_count: int, base_delay: float = 1.0, max_delay: float = 60.0
    ) -> None:
        """Apply exponential backoff with jitter"""
        delay = min(base_delay * (2**retry_count) + random.uniform(0, 1), max_delay)
        await asyncio.sleep(delay)

    async def _process_with_timeout(
        self, coro: Coroutine[Any, Any, T], timeout_seconds: int | None = None
    ) -> T:
        """Wrapper to add timeout protection to file processing

        Args:
            coro: Coroutine to execute with timeout
            timeout_seconds: Timeout in seconds (uses self.ingestion_timeout if None)

        Returns:
            The result of the coroutine

        Raises:
            IngestionTimeoutError: If processing exceeds timeout
        """
        timeout: int = timeout_seconds or self.ingestion_timeout
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            raise IngestionTimeoutError(f"File processing timed out after {timeout} seconds.") from None

    async def create_upload_task(
        self,
        user_id: str,
        file_paths: list,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
    ) -> str:
        """Create a new upload task for bulk file processing"""
        # Use default DocumentFileProcessor with user context
        from models.processors import DocumentFileProcessor

        processor = DocumentFileProcessor(
            self.document_service,
            owner_user_id=user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )
        return await self.create_custom_task(user_id, file_paths, processor)

    async def create_langflow_upload_task(
        self,
        user_id: str,
        file_paths: list,
        langflow_file_service,
        session_manager,
        original_filenames: dict | None = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        session_id: str = None,
        tweaks: dict = None,
        settings: dict = None,
        delete_after_ingest: bool = True,
        replace_duplicates: bool = False,
    ) -> str:
        """Create a new upload task for Langflow file processing with upload and ingest"""
        # Use LangflowFileProcessor with user context
        from models.processors import LangflowFileProcessor

        processor = LangflowFileProcessor(
            langflow_file_service=langflow_file_service,
            session_manager=session_manager,
            owner_user_id=user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
            session_id=session_id,
            tweaks=tweaks,
            settings=settings,
            delete_after_ingest=delete_after_ingest,
            replace_duplicates=replace_duplicates,
        )
        return await self.create_custom_task(user_id, file_paths, processor, original_filenames)

    async def create_custom_task(self, user_id: str, items: list, processor, original_filenames: dict | None = None) -> str:
        """Create a new task with custom processor for any type of items"""
        import os
        # Store anonymous tasks under a stable key so they can be retrieved later
        store_user_id = user_id or AnonymousUser().user_id
        task_id = str(uuid.uuid4())

        # Create file tasks with original filenames if provided
        normalized_originals = (
            {str(k): v for k, v in original_filenames.items()} if original_filenames else {}
        )
        file_tasks = {
            str(item): FileTask(
                file_path=str(item),
                filename=normalized_originals.get(
                    str(item), os.path.basename(str(item))
                ),
            )
            for item in items
        }

        upload_task = UploadTask(
            task_id=task_id,
            total_files=len(items),
            file_tasks=file_tasks,
        )

        # Attach the custom processor to the task
        upload_task.processor = processor

        if store_user_id not in self.task_store:
            self.task_store[store_user_id] = {}
        self.task_store[store_user_id][task_id] = upload_task

        # Start background processing
        background_task = asyncio.create_task(
            self.background_custom_processor(store_user_id, task_id, items)
        )
        self.background_tasks.add(background_task)
        background_task.add_done_callback(self.background_tasks.discard)

        # Store reference to background task for cancellation
        upload_task.background_task = background_task

        # Send telemetry event for task creation with metadata
        asyncio.create_task(
            TelemetryClient.send_event(
                Category.TASK_OPERATIONS,
                MessageId.ORB_TASK_CREATED,
                metadata={
                    "total_files": len(items),
                    "processor_type": processor.__class__.__name__,
                }
            )
        )

        return task_id

    def _get_display_filenames(self, upload_task: UploadTask) -> list[str]:
        filenames: list[str] = [
            task.filename or os.path.basename(task.file_path)
            for task in upload_task.file_tasks.values()
        ]

        if len(filenames) <= 3:
            # e.g. ['book-1.xlsx']
            # e.g. ['book-1.xlsx', 'book-2.xlsx', 'book-3.xlsx']
            return filenames
        # e.g. ['book-1.xlsx', 'book-2.xlsx', 'book-3.xlsx', '...']
        return filenames[:3] + ["..."]

    def _format_duration(self, duration: float | int) -> str:
        """
        Convert specified duration (seconds) into a human-readable string:
        - < 60 s     → "45s"
        - < 60 min   → "3m 42s"
        - ≥ 60 min   → "2h 14m 35s"
        """
        total_seconds: int = max(0, int(duration))

        if total_seconds < 60:
            return f"{total_seconds}s"

        mins, secs = divmod(total_seconds, 60)

        if mins < 60:
            return f"{mins}m {secs}s"

        hours, mins = divmod(mins, 60)

        return f"{hours}h {mins}m {secs}s"

    async def background_custom_processor(
        self, user_id: str, task_id: str, items: list
    ) -> None:
        """Background task to process items using custom processor"""
        try:
            upload_task: UploadTask = self.task_store[user_id][task_id]
            upload_task.status = TaskStatus.RUNNING
            upload_task.updated_at = time.time()

            processor = upload_task.processor

            logger.info(
                "Upload / ingestion task started",
                task_number=upload_task.sequence_number,
                task_id=task_id,
                total_files=upload_task.total_files,
                filenames=self._get_display_filenames(upload_task),
                processor_type=processor.__class__.__name__,
                user_id=user_id,
                worker_count=self._worker_count,
            )

            # Process items with limited concurrency using the global semaphore
            # - Limits concurrency across all tasks, not just within this one
            # - Potential bottlenecks related to downstream Langflow / Docling capacity rather than backend I/O
            async def process_with_semaphore(item, item_key: str):
                async with self._processing_semaphore:
                    file_task = upload_task.file_tasks[item_key]
                    file_task.status = TaskStatus.RUNNING
                    file_task.updated_at = time.time()

                    logger.info(
                        "File processing task running",
                        task_number=upload_task.sequence_number,
                        task_id=task_id,
                        file_path=file_task.file_path,
                    )

                    try:
                        # Add timeout protection to prevent indefinite hangs
                        await self._process_with_timeout(
                            processor.process_item(upload_task, item, file_task),
                            timeout_seconds=self.ingestion_timeout
                        )

                        logger.info(
                            "File processing task succeeded",
                            status="PASSED",
                            task_number=upload_task.sequence_number,
                            task_id=task_id,
                            file_path=file_task.file_path,
                        )

                    except asyncio.CancelledError:
                        # Handle cancellation explicitly

                        if file_task.status == TaskStatus.RUNNING:
                            file_task.status = TaskStatus.FAILED
                            file_task.error = "File processing task cancelled."
                            async with self._get_task_lock(task_id):
                                upload_task.failed_files += 1

                        logger.warning(
                            "File processing task cancelled",
                            status="FAILED",
                            task_number=upload_task.sequence_number,
                            task_id=task_id,
                            file_path=file_task.file_path,
                        )

                        raise  # Re-raise to propagate cancellation
                    except IngestionTimeoutError as e:
                        # Handle timeout explicitly
                        if file_task.status == TaskStatus.RUNNING:
                            file_task.status = TaskStatus.FAILED
                            file_task.error = str(e)
                            async with self._get_task_lock(task_id):
                                upload_task.failed_files += 1
                        # Don't re-raise - treat as normal failure, not cancellation

                        logger.error(
                            "File processing task timed out",
                            status="FAILED",
                            task_number=upload_task.sequence_number,
                            task_id=task_id,
                            file_path=file_task.file_path,
                            exception=str(e),
                        )

                    except Exception as e:
                        # Note: Processors already handle incrementing failed_files and
                        # setting file_task status/error, so we don't duplicate that here.
                        # Only update timestamp if processor didn't already set it
                        if file_task.status == TaskStatus.RUNNING:
                            file_task.status = TaskStatus.FAILED
                        if not file_task.error:
                            file_task.error = str(e)

                        logger.error(
                            "File processing task exception encountered",
                            status="FAILED",
                            task_number=upload_task.sequence_number,
                            task_id=task_id,
                            file_path=file_task.file_path,
                            exception=str(e),
                        )

                    finally:
                        file_task.updated_at = time.time()
                        # Only increment processed_files if the file reached a terminal state
                        # This prevents counter inconsistency on cancellation
                        if file_task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                            async with self._get_task_lock(task_id):
                                upload_task.processed_files += 1
                        upload_task.updated_at = time.time()

            tasks = [process_with_semaphore(item, str(item)) for item in items]

            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark task as completed
            upload_task.status = TaskStatus.COMPLETED
            upload_task.updated_at = time.time()

            status: str = "FAILED"

            if upload_task.failed_files == 0:
                status = "PASSED"
            elif upload_task.successful_files > 0:
                status = "FAILED (partial success)"

            logger.info(
                "Upload / ingestion task finished",
                status=status,
                task_number=upload_task.sequence_number,
                task_id=task_id,
                duration=self._format_duration(upload_task.duration_seconds),
                total_files=upload_task.total_files,
                processed_files=upload_task.processed_files,
                successful_files=upload_task.successful_files,
                failed_files=upload_task.failed_files,
                filenames=self._get_display_filenames(upload_task),
                processor_type=processor.__class__.__name__,
                user_id=user_id,
                worker_count=self._worker_count,
            )

            # Send telemetry for task completion
            asyncio.create_task(
                TelemetryClient.send_event(
                    Category.TASK_OPERATIONS,
                    MessageId.ORB_TASK_COMPLETE,
                    metadata={
                        "total_files": upload_task.total_files,
                        "successful_files": upload_task.successful_files,
                        "failed_files": upload_task.failed_files,
                    }
                )
            )

        except asyncio.CancelledError:
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                # Task status and pending files already handled by cancel_task()
                upload_task = self.task_store[user_id][task_id]

                logger.warning(
                    "Upload / ingestion task cancelled",
                    status="FAILED",
                    task_number=upload_task.sequence_number,
                    task_id=task_id,
                    duration=self._format_duration(upload_task.duration_seconds),
                    total_files=upload_task.total_files,
                    processed_files=upload_task.processed_files,
                    successful_files=upload_task.successful_files,
                    failed_files=upload_task.failed_files,
                    filenames=self._get_display_filenames(upload_task),
                    processor_type=upload_task.processor.__class__.__name__,
                    user_id=user_id,
                    worker_count=self._worker_count,
                )
            else:
                logger.warning(
                    "Upload / ingestion task cancelled",
                    status="FAILED",
                    task_id=task_id,
                    user_id=user_id,
                    worker_count=self._worker_count,
                )

            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                upload_task = self.task_store[user_id][task_id]
                upload_task.status = TaskStatus.FAILED
                upload_task.updated_at = time.time()

                logger.error(
                    "Upload / ingestion task exception encountered",
                    status="FAILED",
                    task_number=upload_task.sequence_number,
                    task_id=task_id,
                    duration=self._format_duration(upload_task.duration_seconds),
                    total_files=upload_task.total_files,
                    processed_files=upload_task.processed_files,
                    successful_files=upload_task.successful_files,
                    failed_files=upload_task.failed_files,
                    filenames=self._get_display_filenames(upload_task),
                    processor_type=upload_task.processor.__class__.__name__,
                    user_id=user_id,
                    worker_count=self._worker_count,
                    exception=str(e),
                )

                # Send telemetry for task failure
                asyncio.create_task(
                    TelemetryClient.send_event(
                        Category.TASK_OPERATIONS,
                        MessageId.ORB_TASK_FAILED,
                        metadata={
                            "total_files": upload_task.total_files,
                            "processed_files": upload_task.processed_files,
                            "successful_files": upload_task.successful_files,
                            "failed_files": upload_task.failed_files,
                        }
                    )
                )
            else:
                logger.error(
                    "Upload / ingestion exception encountered",
                    status="FAILED",
                    task_id=task_id,
                    user_id=user_id,
                    worker_count=self._worker_count,
                    exception=str(e),
                )

    def get_task_status(self, user_id: str, task_id: str) -> dict | None:
        """Get the status of a specific upload task

        Includes fallback to shared tasks stored under the "anonymous" user key
        so default system tasks are visible to all users.
        """
        if not task_id:
            return None

        # Prefer the caller's user_id; otherwise check shared/anonymous tasks
        candidate_user_ids = [user_id, AnonymousUser().user_id]

        upload_task = None
        for candidate_user_id in candidate_user_ids:
            if (
                candidate_user_id in self.task_store
                and task_id in self.task_store[candidate_user_id]
            ):
                upload_task = self.task_store[candidate_user_id][task_id]
                break

        if upload_task is None:
            return None

        file_statuses = {}
        running_files_count = 0
        pending_files_count = 0

        for file_path, file_task in upload_task.file_tasks.items():
            file_statuses[file_path] = {
                "status": file_task.status.value,
                "result": file_task.result,
                "error": file_task.error,
                "retry_count": file_task.retry_count,
                "created_at": file_task.created_at,
                "updated_at": file_task.updated_at,
                "duration_seconds": file_task.duration_seconds,
                "filename": file_task.filename,
            }

            # Count running and pending files
            if file_task.status.value == "running":
                running_files_count += 1
            elif file_task.status.value == "pending":
                pending_files_count += 1

        return {
            "task_id": upload_task.task_id,
            "status": upload_task.status.value,
            "total_files": upload_task.total_files,
            "processed_files": upload_task.processed_files,
            "successful_files": upload_task.successful_files,
            "failed_files": upload_task.failed_files,
            "running_files": running_files_count,
            "pending_files": pending_files_count,
            "created_at": upload_task.created_at,
            "updated_at": upload_task.updated_at,
            "duration_seconds": upload_task.duration_seconds,
            "files": file_statuses,
        }

    def get_all_tasks(self, user_id: str) -> list:
        """Get all tasks for a user

        Returns the union of the user's own tasks and shared default tasks stored
        under the "anonymous" user key. User-owned tasks take precedence
        if a task_id overlaps.
        """
        tasks_by_id = {}

        def add_tasks_from_store(store_user_id):
            if store_user_id not in self.task_store:
                return
            for task_id, upload_task in self.task_store[store_user_id].items():
                if task_id in tasks_by_id:
                    continue

                # Calculate running and pending counts and build file statuses
                running_files_count = 0
                pending_files_count = 0
                file_statuses = {}

                for file_path, file_task in upload_task.file_tasks.items():
                    if file_task.status.value != "completed":
                        file_statuses[file_path] = {
                            "status": file_task.status.value,
                            "result": file_task.result,
                            "error": file_task.error,
                            "retry_count": file_task.retry_count,
                            "created_at": file_task.created_at,
                            "updated_at": file_task.updated_at,
                            "duration_seconds": file_task.duration_seconds,
                            "filename": file_task.filename,
                        }

                    if file_task.status.value == "running":
                        running_files_count += 1
                    elif file_task.status.value == "pending":
                        pending_files_count += 1

                tasks_by_id[task_id] = {
                    "task_id": upload_task.task_id,
                    "status": upload_task.status.value,
                    "total_files": upload_task.total_files,
                    "processed_files": upload_task.processed_files,
                    "successful_files": upload_task.successful_files,
                    "failed_files": upload_task.failed_files,
                    "running_files": running_files_count,
                    "pending_files": pending_files_count,
                    "created_at": upload_task.created_at,
                    "updated_at": upload_task.updated_at,
                    "duration_seconds": upload_task.duration_seconds,
                    "files": file_statuses,
                }

        # First, add user-owned tasks; then shared anonymous;
        add_tasks_from_store(user_id)
        add_tasks_from_store(AnonymousUser().user_id)

        tasks = list(tasks_by_id.values())
        tasks.sort(key=lambda x: x["created_at"], reverse=True)
        return tasks

    async def cleanup_old_tasks(self, max_age_seconds: int = 3600) -> int:
        """Remove completed/failed tasks older than max_age_seconds

        Args:
            max_age_seconds: Maximum age in seconds for completed tasks (default: 1 hour)

        Returns:
            Number of tasks cleaned up
        """
        current_time = time.time()
        cleaned_count = 0

        # Complexity Analysis:
        # O(n) where n = total tasks across all users

        for user_id in list(self.task_store.keys()):
            for task_id in list(self.task_store[user_id].keys()):
                task = self.task_store[user_id][task_id]
                # Only cleanup completed or failed tasks that are old enough
                if (task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and
                    current_time - task.updated_at > max_age_seconds):
                    del self.task_store[user_id][task_id]
                    # Clean up the associated lock
                    self._task_locks.pop(task_id, None)
                    cleaned_count += 1
                    logger.debug(
                        "Cleaned up old task",
                        task_id=task_id,
                        user_id=user_id,
                        age_seconds=current_time - task.updated_at
                    )

            # Remove empty user entries
            if not self.task_store[user_id]:
                del self.task_store[user_id]

        if cleaned_count > 0:
            logger.info("Task cleanup completed", cleaned_count=cleaned_count)

        return cleaned_count

    async def cancel_task(self, user_id: str, task_id: str) -> bool:
        """Cancel a task if it exists and is not already completed.

        Supports cancellation of shared default tasks stored under the anonymous user.
        """
        # Check candidate user IDs first, then anonymous to find which user ID the task is mapped to
        candidate_user_ids = [user_id, AnonymousUser().user_id]

        store_user_id = None
        for candidate_user_id in candidate_user_ids:
            if (
                candidate_user_id in self.task_store
                and task_id in self.task_store[candidate_user_id]
            ):
                store_user_id = candidate_user_id
                break

        if store_user_id is None:
            return False

        upload_task = self.task_store[store_user_id][task_id]

        # Can only cancel pending or running tasks
        if upload_task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            return False

        # Cancel the background task to stop scheduling new work
        if (
            hasattr(upload_task, "background_task")
            and not upload_task.background_task.done()
        ):
            upload_task.background_task.cancel()
            # Wait for the background task to actually stop to avoid race conditions
            try:
                await upload_task.background_task
            except asyncio.CancelledError:
                pass  # Expected when we cancel the task
            except Exception:
                pass  # Ignore other errors during cancellation

        # Mark task as failed (cancelled)
        upload_task.status = TaskStatus.FAILED
        upload_task.updated_at = time.time()

        # Mark all pending and running file tasks as failed
        for file_task in upload_task.file_tasks.values():
            # Lock the entire check-and-modify to prevent race with background tasks
            async with self._get_task_lock(task_id):
                if file_task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    # Increment failed_files counter for both pending and running
                    # (running files haven't been counted yet in either counter)
                    upload_task.failed_files += 1
                    file_task.status = TaskStatus.FAILED
                    file_task.error = "Task cancelled by user"
                    file_task.updated_at = time.time()

        return True

    async def shutdown(self):
        """Cleanup process pool and cancel all background tasks

        Ensures graceful shutdown by:
        1. Cancelling the periodic cleanup task
        2. Cancelling all running background tasks
        3. Waiting for cancellation to complete
        4. Shutting down the process pool
        """
        logger.info("Shutting down TaskService", background_tasks_count=len(self.background_tasks))

        # Cancel the periodic cleanup task
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel all background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete cancellation
        if self.background_tasks:
            results = await asyncio.gather(*self.background_tasks, return_exceptions=True)
            # Log any unexpected errors (not CancelledError)
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.warning("Background task raised exception during shutdown", error=str(result))

        # Shutdown the process pool
        if hasattr(self, "process_pool"):
            self.process_pool.shutdown(wait=True)
            logger.info("Process pool shutdown complete")
