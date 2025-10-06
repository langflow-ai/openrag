import asyncio
import random
import time
import uuid

from models.tasks import FileTask, TaskStatus, UploadTask
from session_manager import AnonymousUser
from utils.gpu_detection import get_worker_count
from utils.logging_config import get_logger


logger = get_logger(__name__)


class TaskService:
    def __init__(self, document_service=None, process_pool=None):
        self.document_service = document_service
        self.process_pool = process_pool
        self.task_store: dict[
            str, dict[str, UploadTask]
        ] = {}  # user_id -> {task_id -> UploadTask}
        self.background_tasks = set()

        if self.process_pool is None:
            raise ValueError("TaskService requires a process_pool parameter")

    async def exponential_backoff_delay(
        self, retry_count: int, base_delay: float = 1.0, max_delay: float = 60.0
    ) -> None:
        """Apply exponential backoff with jitter"""
        delay = min(base_delay * (2**retry_count) + random.uniform(0, 1), max_delay)
        await asyncio.sleep(delay)

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

        return task_id

    async def background_upload_processor(self, user_id: str, task_id: str) -> None:
        """Background task to process all files in an upload job with concurrency control"""
        try:
            upload_task = self.task_store[user_id][task_id]
            upload_task.status = TaskStatus.RUNNING
            upload_task.updated_at = time.time()

            # Process files with limited concurrency to avoid overwhelming the system
            max_workers = get_worker_count()
            semaphore = asyncio.Semaphore(
                max_workers * 2
            )  # Allow 2x process pool size for async I/O

            async def process_with_semaphore(file_path: str):
                async with semaphore:
                    from models.processors import DocumentFileProcessor
                    file_task = upload_task.file_tasks[file_path]

                    # Create processor with user context (all None for background processing)
                    processor = DocumentFileProcessor(
                        document_service=self.document_service,
                        owner_user_id=None,
                        jwt_token=None,
                        owner_name=None,
                        owner_email=None,
                    )

                    # Process the file
                    await processor.process_item(upload_task, file_path, file_task)

            tasks = [
                process_with_semaphore(file_path)
                for file_path in upload_task.file_tasks.keys()
            ]

            await asyncio.gather(*tasks, return_exceptions=True)

            # Check if task is complete
            if upload_task.processed_files >= upload_task.total_files:
                upload_task.status = TaskStatus.COMPLETED
                upload_task.updated_at = time.time()

        except Exception as e:
            logger.error(
                "Background upload processor failed", task_id=task_id, error=str(e)
            )
            import traceback

            traceback.print_exc()
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                self.task_store[user_id][task_id].status = TaskStatus.FAILED
                self.task_store[user_id][task_id].updated_at = time.time()

    async def background_custom_processor(
        self, user_id: str, task_id: str, items: list
    ) -> None:
        """Background task to process items using custom processor"""
        try:
            upload_task = self.task_store[user_id][task_id]
            upload_task.status = TaskStatus.RUNNING
            upload_task.updated_at = time.time()

            processor = upload_task.processor

            # Process items with limited concurrency
            max_workers = get_worker_count()
            semaphore = asyncio.Semaphore(max_workers * 2)

            async def process_with_semaphore(item, item_key: str):
                async with semaphore:
                    file_task = upload_task.file_tasks[item_key]
                    file_task.status = TaskStatus.RUNNING
                    file_task.updated_at = time.time()

                    try:
                        await processor.process_item(upload_task, item, file_task)
                    except Exception as e:
                        logger.error(
                            "Failed to process item", item=str(item), error=str(e)
                        )
                        import traceback

                        traceback.print_exc()
                        file_task.status = TaskStatus.FAILED
                        file_task.error = str(e)
                        upload_task.failed_files += 1
                    finally:
                        file_task.updated_at = time.time()
                        upload_task.processed_files += 1
                        upload_task.updated_at = time.time()

            tasks = [process_with_semaphore(item, str(item)) for item in items]

            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark task as completed
            upload_task.status = TaskStatus.COMPLETED
            upload_task.updated_at = time.time()

        except asyncio.CancelledError:
            logger.info("Background processor cancelled", task_id=task_id)
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                # Task status and pending files already handled by cancel_task()
                pass
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(
                "Background custom processor failed", task_id=task_id, error=str(e)
            )
            import traceback

            traceback.print_exc()
            if user_id in self.task_store and task_id in self.task_store[user_id]:
                self.task_store[user_id][task_id].status = TaskStatus.FAILED
                self.task_store[user_id][task_id].updated_at = time.time()

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
            if file_task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                # Increment failed_files counter for both pending and running
                # (running files haven't been counted yet in either counter)
                upload_task.failed_files += 1

                file_task.status = TaskStatus.FAILED
                file_task.error = "Task cancelled by user"
                file_task.updated_at = time.time()

        return True

    def shutdown(self):
        """Cleanup process pool"""
        if hasattr(self, "process_pool"):
            self.process_pool.shutdown(wait=True)
