import asyncio
import os
import random
import time
import traceback
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

from models.tasks import DoclingPhaseStatus, FileTask, IngestionPhase, TaskStatus, UploadTask
from session_manager import AnonymousUser
from utils.gpu_detection import get_worker_count
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

T = TypeVar("T")

logger = get_logger(__name__)

# Substrings that indicate a permanent file/content problem (not worth retrying).
_NON_RETRYABLE_FILE_ERROR_MARKERS = (
    "corrupt",
    "corrupted",
    "corruption",
    "invalid file",
    "invalid document",
    "unsupported format",
    "unsupported file",
    "malformed",
    "damaged",
    "not a zip file",
    "bad zipfile",
    "failed to parse",
    "could not be parsed",
    "cannot parse",
    "no text content could be extracted",
    "empty or unreadable",
    "unreadable",
    "validationerror",
)

# Docling polling errors that are transient (service/timeout), not bad file content.
_DOCLING_TRANSIENT_ERROR_MARKERS = (
    "(timeout)",
    "timed out",
    "polling exceeded",
    "polling timed out",
)

# Connector/download/network failures seen while file is still in Docling phase.
# These are infrastructure/transient and should be retryable.
_TRANSIENT_CONNECTIVITY_ERROR_MARKERS = (
    "all connection attempts failed",
    "connection refused",
    "connection reset",
    "temporary failure in name resolution",
    "name or service not known",
    "service unavailable",
    "network is unreachable",
    "server disconnected",
    "disconnected without sending a response",
    "remote protocol error",
    "broken pipe",
)


def _is_non_retryable_file_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _NON_RETRYABLE_FILE_ERROR_MARKERS)


def _is_transient_connectivity_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _TRANSIENT_CONNECTIVITY_ERROR_MARKERS)


def _is_docling_transient_error(error: str) -> bool:
    lowered = error.lower()
    # Legacy timeout messages emitted by Docling polling path.
    if "docling conversion did not complete" in lowered:
        return any(marker in lowered for marker in _DOCLING_TRANSIENT_ERROR_MARKERS)

    # Connector-originated transient network failures can still surface while
    # file phase is DOCLING (before conversion can complete).
    return _is_transient_connectivity_error(error)


def _transient_connectivity_user_message(error: str) -> str:
    lowered = error.lower()
    if any(
        marker in lowered
        for marker in (
            "disconnect",
            "without sending a response",
            "connection refused",
            "connection reset",
            "broken pipe",
            "remote protocol",
        )
    ):
        return "Ingestion service connection was lost. Please retry ingestion."
    if any(marker in lowered for marker in ("timeout", "timed out")):
        return "Document processing timed out. Please retry ingestion."
    return "Ingestion service was temporarily unavailable. Please retry ingestion."


def _is_langflow_transport_failure(error: str) -> bool:
    """HTTP client / Langflow transport failures on the connector ingest path."""
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "server disconnected",
            "disconnected without sending a response",
            "remote protocol error",
            "read error",
            "write error",
        )
    )


class IngestionTimeoutError(Exception):
    """Raised when file processing exceeds the configured timeout"""

    pass


class TaskService:
    # Cleanup interval in seconds (2 hours)
    CLEANUP_INTERVAL_SECONDS = 2 * 60 * 60

    def __init__(
        self,
        document_service=None,
        models_service=None,
        ingestion_timeout=3600,
        docling_service=None,
        docling_polling_service=None,
        session_manager=None,
    ):
        self.document_service = document_service
        self.models_service = models_service
        self.docling_service = docling_service
        self.session_manager = session_manager
        # Backend-side Docling polling coordinator. Injected by the container
        # so LangflowFileProcessor receives it from the established DI chain
        # rather than constructing it inline. None disables the two-phase
        # flow and falls back to the legacy single-call ingestion path.
        self.docling_polling_service = docling_polling_service
        self.task_store: dict[str, dict[str, UploadTask]] = {}  # user_id -> {task_id -> UploadTask}
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
        except TimeoutError:
            raise IngestionTimeoutError(
                f"File processing timed out after {timeout} seconds."
            ) from None

    async def create_upload_task(
        self,
        user_id: str,
        file_paths: list,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        original_filenames: dict | None = None,
        replace_duplicates: bool = False,
        settings: dict | None = None,
    ) -> str:
        """Create a new upload task for bulk file processing"""
        # Use default DocumentFileProcessor with user context
        from models.processors import DocumentFileProcessor

        processor = DocumentFileProcessor(
            self.document_service,
            models_service=self.models_service,
            owner_user_id=user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
            docling_service=self.docling_service,
            replace_duplicates=replace_duplicates,
            session_manager=self.session_manager,
            settings=settings,
        )
        return await self.create_custom_task(
            user_id,
            file_paths,
            processor,
            original_filenames=original_filenames,
            temp_file_paths=file_paths,
        )

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
        replace_duplicates: bool = False,
        connector_type: str = "local",
        existing_task_id: str = None,
        temp_file_paths: list | None = None,
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
            replace_duplicates=replace_duplicates,
            connector_type=connector_type,
            docling_polling_service=self.docling_polling_service,
        )
        return await self.create_custom_task(
            user_id,
            file_paths,
            processor,
            original_filenames,
            existing_task_id=existing_task_id,
            temp_file_paths=temp_file_paths if temp_file_paths is not None else file_paths,
        )

    async def create_langflow_url_upload_task(
        self,
        owner_user_id: str,
        docs_url: str,
        crawl_depth: int,
        langflow_file_service,
        session_manager,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        connector_type: str = "openrag_docs",
        prevent_outside: bool = True,
        tweaks: dict = None,
        existing_task_id: str = None,
    ) -> str:
        """Create a new upload task for Langflow URL ingestion."""
        from models.url import LangflowUrlProcessor

        processor = LangflowUrlProcessor(
            langflow_file_service=langflow_file_service,
            session_manager=session_manager,
            docs_url=docs_url,
            crawl_depth=crawl_depth,
            owner_user_id=owner_user_id,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
            connector_type=connector_type,
            prevent_outside=prevent_outside,
            tweaks=tweaks,
        )
        return await self.create_custom_task(
            owner_user_id, [docs_url], processor, existing_task_id=existing_task_id
        )

    async def create_custom_task(
        self,
        user_id: str,
        items: list,
        processor,
        original_filenames: dict | None = None,
        existing_task_id: str = None,
        temp_file_paths: list | None = None,
    ) -> str:
        """Create a new task with custom processor for any type of items"""
        import os

        # Store anonymous tasks under a stable key so they can be retrieved later
        store_user_id = user_id or AnonymousUser().user_id
        task_id = existing_task_id or str(uuid.uuid4())

        # Create file tasks with original filenames if provided
        normalized_originals = (
            {str(k): v for k, v in original_filenames.items()} if original_filenames else {}
        )
        file_tasks = {
            str(item): FileTask(
                file_path=str(item),
                filename=normalized_originals.get(str(item), os.path.basename(str(item))),
            )
            for item in items
        }

        if (
            existing_task_id
            and store_user_id in self.task_store
            and existing_task_id in self.task_store[store_user_id]
        ):
            upload_task = self.task_store[store_user_id][existing_task_id]
            upload_task.file_tasks.update(file_tasks)
            upload_task.total_files += len(items)
            upload_task.status = TaskStatus.RUNNING
        else:
            upload_task = UploadTask(
                task_id=task_id,
                total_files=len(items),
                file_tasks=file_tasks,
            )
            upload_task.processor = processor
            if store_user_id not in self.task_store:
                self.task_store[store_user_id] = {}
            self.task_store[store_user_id][task_id] = upload_task

        # Store temp file paths for cleanup after processing
        if temp_file_paths:
            if upload_task.temp_file_paths is None:
                upload_task.temp_file_paths = []
            normalized_temp_paths = [str(path) for path in temp_file_paths]
            unknown_temp_paths = [
                path for path in normalized_temp_paths if path not in upload_task.file_tasks
            ]
            if unknown_temp_paths:
                logger.warning(
                    "temp_file_paths do not match file_tasks keys; retry retention may fail",
                    task_id=task_id,
                    unknown_temp_paths=unknown_temp_paths,
                )
            upload_task.temp_file_paths.extend(normalized_temp_paths)

        # Start background processing
        background_task = asyncio.create_task(
            self.background_custom_processor(store_user_id, task_id, items, processor)
        )
        self.background_tasks.add(background_task)
        background_task.add_done_callback(self.background_tasks.discard)

        # Store reference to background task for cancellation if newly created
        if not existing_task_id:
            upload_task.background_task = background_task

        # Send telemetry event for task creation with metadata
        asyncio.create_task(
            TelemetryClient.send_event(
                Category.TASK_OPERATIONS,
                MessageId.ORB_TASK_CREATED,
                metadata={
                    "total_files": len(items),
                    "processor_type": processor.__class__.__name__,
                },
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
        self, user_id: str, task_id: str, items: list, processor=None
    ) -> None:
        """Background task to process items using custom processor"""
        try:
            upload_task: UploadTask = self.task_store[user_id][task_id]
            upload_task.status = TaskStatus.RUNNING
            upload_task.updated_at = time.time()

            processor = processor or upload_task.processor

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
                            timeout_seconds=self.ingestion_timeout,
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
                            traceback=traceback.format_exc(),
                            task_number=upload_task.sequence_number,
                            task_id=task_id,
                            file_path=file_task.file_path,
                            exception=str(e),
                        )

                    finally:
                        file_task.updated_at = time.time()
                        # Only increment processed_files if the file reached a terminal state
                        # This prevents counter inconsistency on cancellation.
                        # SKIPPED is terminal too — e.g. source-deleted files in
                        # connector sync — and must count, or the upload task
                        # never reaches processed_files >= total_files and stays
                        # open forever.
                        if file_task.status in [
                            TaskStatus.COMPLETED,
                            TaskStatus.FAILED,
                            TaskStatus.SKIPPED,
                        ]:
                            async with self._get_task_lock(task_id):
                                upload_task.processed_files += 1
                        upload_task.updated_at = time.time()

            tasks = [process_with_semaphore(item, str(item)) for item in items]

            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark task as completed if all files (including appended ones) are done
            if upload_task.processed_files >= upload_task.total_files:
                # Force an index refresh BEFORE marking the task COMPLETED so that
                # callers polling for COMPLETED status can immediately query or delete
                # the newly indexed chunks without hitting the near-real-time refresh window.
                if upload_task.successful_files > 0:
                    try:
                        from config.settings import clients, get_index_name

                        await clients.opensearch.indices.refresh(index=get_index_name())
                    except Exception as e:
                        logger.debug("Index refresh after ingest failed (non-fatal)", error=str(e))

                upload_task.status = TaskStatus.COMPLETED
                upload_task.updated_at = time.time()

            # Clean up upload temps that are not retryable; keep local RETRYABLE
            # failures so retry can re-read the staged source file.
            self._cleanup_upload_temp_files(upload_task)

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
                    },
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
                        },
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

    def _resolve_upload_task(self, user_id: str, task_id: str) -> UploadTask | None:
        """Look up a task by ID, falling back to anonymous/shared tasks."""
        if not task_id:
            return None
        for candidate_user_id in [user_id, AnonymousUser().user_id]:
            if (
                candidate_user_id in self.task_store
                and task_id in self.task_store[candidate_user_id]
            ):
                return self.task_store[candidate_user_id][task_id]
        return None

    def _resolve_upload_task_store(
        self, user_id: str, task_id: str
    ) -> tuple[str, UploadTask] | None:
        """Return (store_user_id, upload_task) for a task visible to this user."""
        if not task_id:
            return None
        for candidate_user_id in [user_id, AnonymousUser().user_id]:
            if (
                candidate_user_id in self.task_store
                and task_id in self.task_store[candidate_user_id]
            ):
                return candidate_user_id, self.task_store[candidate_user_id][task_id]
        return None

    async def retry_failed_files(
        self,
        user_id: str,
        task_id: str,
        *,
        file_paths: list[str] | None = None,
        retryable_only: bool = True,
    ) -> dict | None:
        """Re-queue failed files for ingestion when their source paths still exist.

        Only files classified as RETRYABLE are retried when *retryable_only* is
        True (the default). When *file_paths* is set, only those task paths are
        considered; paths missing from the task or not in a failed state are
        reported in *skipped*. This reuses the task's original processor — it
        does not accept new uploads from the client.

        Connector tasks often use provider IDs (not local absolute paths) as
        ``file_path`` keys. For those non-absolute identifiers, skip local
        filesystem existence checks and let the connector processor re-fetch.
        """
        resolved = self._resolve_upload_task_store(user_id, task_id)
        if resolved is None:
            return None

        store_user_id, upload_task = resolved

        paths_to_retry: list[str] = []
        skipped: list[dict] = []
        requested_paths = set(file_paths) if file_paths is not None else None

        # Keep status checks, candidate selection, and state transitions inside
        # one lock to avoid concurrent retry requests enqueueing duplicates.
        async with self._get_task_lock(task_id):
            processor = upload_task.processor
            if upload_task.status == TaskStatus.RUNNING:
                return {
                    "error": "task_in_progress",
                    "message": "Task is still running",
                    "task_id": task_id,
                }

            if processor is None:
                return {
                    "error": "no_processor",
                    "message": "Cannot retry: task processor is no longer available",
                    "task_id": task_id,
                }

            if requested_paths is not None:
                for path in requested_paths:
                    file_task = upload_task.file_tasks.get(path)
                    if file_task is None:
                        skipped.append({"file_path": path, "reason": "file_not_in_task"})
                    elif file_task.status != TaskStatus.FAILED:
                        skipped.append(
                            {
                                "file_path": path,
                                "filename": file_task.filename,
                                "reason": "not_failed",
                            }
                        )

            # Build retry candidates before mutating shared task/file state.
            retry_candidates: list[tuple[str, FileTask]] = []
            for file_path, file_task in list(upload_task.file_tasks.items()):
                if requested_paths is not None and file_path not in requested_paths:
                    continue
                if file_task.status != TaskStatus.FAILED:
                    continue

                if retryable_only:
                    metadata = self._infer_failure_metadata(file_task)
                    if not metadata or metadata.get("actionable_by") != "RETRYABLE":
                        skipped.append(
                            {
                                "file_path": file_path,
                                "filename": file_task.filename,
                                "reason": "not_retryable",
                            }
                        )
                        continue

                # Only enforce local source-file existence for absolute paths.
                # Connector-backed tasks typically store remote IDs as file_path.
                if os.path.isabs(file_path) and not os.path.isfile(file_path):
                    skipped.append(
                        {
                            "file_path": file_path,
                            "filename": file_task.filename,
                            "reason": "source_file_missing",
                        }
                    )
                    continue

                retry_candidates.append((file_path, file_task))

            now = time.time()
            for file_path, file_task in retry_candidates:
                if upload_task.failed_files > 0:
                    upload_task.failed_files -= 1
                if upload_task.processed_files > 0:
                    upload_task.processed_files -= 1

                file_task.status = TaskStatus.PENDING
                file_task.error = None
                file_task.result = None
                file_task.retry_count += 1
                file_task.docling_task_id = None
                # Connector tasks use remote IDs as file_path and ingest via Langflow.
                if os.path.isabs(file_path):
                    file_task.docling_status = DoclingPhaseStatus.PENDING
                    file_task.phase = IngestionPhase.DOCLING
                else:
                    file_task.docling_status = DoclingPhaseStatus.PENDING
                    file_task.phase = IngestionPhase.LANGFLOW
                file_task.updated_at = now
                paths_to_retry.append(file_path)

            if paths_to_retry:
                upload_task.status = TaskStatus.RUNNING
                upload_task.updated_at = now

        if not paths_to_retry:
            return {
                "task_id": task_id,
                "retried": 0,
                "skipped": skipped,
                "status": "no_op",
                "message": "No retryable files with available source data",
            }

        background_task = asyncio.create_task(
            self.background_custom_processor(store_user_id, task_id, paths_to_retry, processor)
        )
        upload_task.background_task = background_task
        self.background_tasks.add(background_task)

        def _clear_retry_background_task(done_task: asyncio.Task) -> None:
            self.background_tasks.discard(done_task)
            if upload_task.background_task is done_task:
                upload_task.background_task = None

        background_task.add_done_callback(_clear_retry_background_task)

        return {
            "task_id": task_id,
            "retried": len(paths_to_retry),
            "skipped": skipped,
            "status": "accepted",
        }

    def _serialize_file_task(self, file_task: FileTask) -> dict:
        """Serialize a FileTask to the standard dict shape."""
        return {
            "status": file_task.status.value,
            "result": file_task.result,
            "error": file_task.error,
            "retry_count": file_task.retry_count,
            "created_at": file_task.created_at,
            "updated_at": file_task.updated_at,
            "duration_seconds": file_task.duration_seconds,
            "filename": file_task.filename,
            "phase": file_task.phase.value,
            "docling_status": file_task.docling_status.value,
            "docling_task_id": file_task.docling_task_id,
        }

    def _infer_failure_metadata(self, file_task: FileTask) -> dict | None:
        """Infer structured failure metadata for a failed FileTask.

        Returns a dict with component, failure_phase, user_facing_message, and
        actionable_by when the failure can be classified, or None when the cause
        is unknown and no fields should be emitted.

        Priority order: transient / retryable docling outcomes (expired, polling
        timeout) before generic docling FAILED, which indicates conversion failure.
        """
        docling_status = file_task.docling_status
        phase = file_task.phase
        error = file_task.error or ""

        if docling_status == DoclingPhaseStatus.EXPIRED:
            return {
                "component": "docling",
                "failure_phase": "parsing",
                "user_facing_message": (
                    "The document processing result could not be found. "
                    "The task may have expired. Please retry ingestion."
                ),
                "actionable_by": "RETRYABLE",
            }

        # First, check if the error is non-retryable based on common markers
        if _is_non_retryable_file_error(error):
            if phase == IngestionPhase.LANGFLOW:
                component = "langflow"
                failure_phase = "unknown"
            else:
                component = "docling"
                failure_phase = "parsing"

            # Extract detailed error message if possible, otherwise default to corrupted/invalid msg
            msg = (
                "The file appears corrupted or invalid and cannot be processed. "
                "Upload a valid file."
            )
            if "Docling result unavailable after SUCCESS status: " in error:
                msg = error.split("Docling result unavailable after SUCCESS status: ", 1)[1]
            elif "Docling conversion did not complete" in error:
                sub_msg = error.split("Docling conversion did not complete", 1)[1]
                if sub_msg.startswith(" (failed): "):
                    msg = sub_msg[len(" (failed): ") :]
                else:
                    msg = sub_msg.strip(" ():")

            return {
                "component": component,
                "failure_phase": failure_phase,
                "user_facing_message": msg,
                "actionable_by": "USER_ACTIONABLE",
            }

        # Handle docling conversion completion issues (failed / timeout)
        if phase == IngestionPhase.DOCLING and "Docling conversion did not complete" in error:
            user_facing_message = "Document processing timed out. Please retry ingestion."
            if "timeout" not in error.lower() and "expired" not in error.lower():
                msg = error.split("Docling conversion did not complete", 1)[1]
                if msg.startswith(" (failed): "):
                    user_facing_message = msg[len(" (failed): ") :]
                elif msg.startswith(" (timeout): "):
                    user_facing_message = "Document processing timed out. Please retry ingestion."
                else:
                    user_facing_message = msg.strip(" ():")
            return {
                "component": "docling",
                "failure_phase": "parsing",
                "user_facing_message": user_facing_message,
                "actionable_by": "RETRYABLE"
                if "timed out" in user_facing_message.lower()
                else "USER_ACTIONABLE",
            }

        if phase == IngestionPhase.DOCLING and _is_docling_transient_error(error):
            langflow_transport = _is_langflow_transport_failure(error)
            return {
                "component": "langflow" if langflow_transport else "docling",
                "failure_phase": "unknown" if langflow_transport else "parsing",
                "user_facing_message": _transient_connectivity_user_message(error),
                "actionable_by": "RETRYABLE",
            }

        if phase == IngestionPhase.DOCLING and docling_status == DoclingPhaseStatus.PROCESSING:
            return {
                "component": "docling",
                "failure_phase": "parsing",
                "user_facing_message": "Document processing timed out. Please retry ingestion.",
                "actionable_by": "RETRYABLE",
            }

        if docling_status == DoclingPhaseStatus.FAILED:
            msg = "The file could not be processed into readable document content."
            if error:
                if "Docling result unavailable after SUCCESS status: " in error:
                    msg = error.split("Docling result unavailable after SUCCESS status: ", 1)[1]
                elif "Docling conversion did not complete" in error:
                    sub_msg = error.split("Docling conversion did not complete", 1)[1]
                    if sub_msg.startswith(" (failed): "):
                        msg = sub_msg[len(" (failed): ") :]
                    else:
                        msg = sub_msg.strip(" ():")
                else:
                    msg = error
            return {
                "component": "docling",
                "failure_phase": "parsing",
                "user_facing_message": msg,
                "actionable_by": "USER_ACTIONABLE",
            }

        if "already exists" in error:
            return {
                "component": "openrag",
                "failure_phase": "file_validation",
                "user_facing_message": "A file with this name already exists.",
                "actionable_by": "USER_ACTIONABLE",
            }

        if _is_transient_connectivity_error(error) or _is_langflow_transport_failure(error):
            return {
                "component": "langflow",
                "failure_phase": "unknown",
                "user_facing_message": _transient_connectivity_user_message(error),
                "actionable_by": "RETRYABLE",
            }

        if phase == IngestionPhase.LANGFLOW:
            error_lower = error.lower()
            if any(
                marker in error_lower
                for marker in ("timeout", "timed out", "unavailable", "connection refused")
            ):
                return {
                    "component": "langflow",
                    "failure_phase": "unknown",
                    "user_facing_message": (
                        "Ingestion timed out or the service was unavailable. Please retry."
                    ),
                    "actionable_by": "RETRYABLE",
                }
            return {
                "component": "langflow",
                "failure_phase": "unknown",
                "user_facing_message": (
                    "Ingestion failed unexpectedly. Please retry. "
                    "If it fails again, contact your administrator."
                ),
                "actionable_by": "RETRYABLE",
            }

        return None

    def get_task_status(self, user_id: str, task_id: str) -> dict | None:
        """Get the status of a specific upload task

        Includes fallback to shared tasks stored under the "anonymous" user key
        so default system tasks are visible to all users.
        """
        upload_task = self._resolve_upload_task(user_id, task_id)

        if upload_task is None:
            return None

        file_statuses = {}
        running_files_count = 0
        pending_files_count = 0

        for file_path, file_task in upload_task.file_tasks.items():
            file_statuses[file_path] = self._serialize_file_task(file_task)

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

    def get_task_status2(self, user_id: str, task_id: str) -> dict | None:
        """Get the status of a specific upload task with structured failure metadata.

        Identical to get_task_status but enriches failed file entries with
        component, failure_phase, user_facing_message, and actionable_by fields
        when the failure cause can be classified.
        """
        upload_task = self._resolve_upload_task(user_id, task_id)

        if upload_task is None:
            return None

        file_statuses = {}
        running_files_count = 0
        pending_files_count = 0

        for file_path, file_task in upload_task.file_tasks.items():
            entry = self._serialize_file_task(file_task)
            if file_task.status == TaskStatus.FAILED:
                metadata = self._infer_failure_metadata(file_task)
                if metadata:
                    entry.update(metadata)
            file_statuses[file_path] = entry

            if file_task.status == TaskStatus.RUNNING:
                running_files_count += 1
            elif file_task.status == TaskStatus.PENDING:
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

    def get_all_tasks2(self, user_id: str) -> list:
        """Get all tasks for a user with structured failure metadata on failed files.

        Identical to get_all_tasks but enriches failed file entries with
        component, failure_phase, user_facing_message, and actionable_by fields
        when the failure cause can be classified.
        """
        tasks_by_id = {}

        def add_tasks_from_store(store_user_id):
            if store_user_id not in self.task_store:
                return
            for task_id, upload_task in self.task_store[store_user_id].items():
                if task_id in tasks_by_id:
                    continue

                running_files_count = 0
                pending_files_count = 0
                file_statuses = {}

                for file_path, file_task in upload_task.file_tasks.items():
                    if file_task.status != TaskStatus.COMPLETED:
                        entry = self._serialize_file_task(file_task)
                        if file_task.status == TaskStatus.FAILED:
                            metadata = self._infer_failure_metadata(file_task)
                            if metadata:
                                entry.update(metadata)
                        file_statuses[file_path] = entry

                    if file_task.status == TaskStatus.RUNNING:
                        running_files_count += 1
                    elif file_task.status == TaskStatus.PENDING:
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

        add_tasks_from_store(user_id)
        add_tasks_from_store(AnonymousUser().user_id)

        tasks = list(tasks_by_id.values())
        tasks.sort(key=lambda x: x["created_at"], reverse=True)
        return tasks

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
                            "phase": file_task.phase.value,
                            "docling_status": file_task.docling_status.value,
                            "docling_task_id": file_task.docling_task_id,
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
                if (
                    task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
                    and current_time - task.updated_at > max_age_seconds
                ):
                    # Task is leaving memory; reclaim any retained upload temps
                    # (including RETRYABLE locals kept for in-flight retry).
                    self._cleanup_upload_temp_files(task, force=True)
                    del self.task_store[user_id][task_id]
                    # Clean up the associated lock
                    self._task_locks.pop(task_id, None)
                    cleaned_count += 1
                    logger.debug(
                        "Cleaned up old task",
                        task_id=task_id,
                        user_id=user_id,
                        age_seconds=current_time - task.updated_at,
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
        if hasattr(upload_task, "background_task") and not upload_task.background_task.done():
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

        self._cleanup_upload_temp_files(upload_task, force=True)

        return True

    def _file_task_for_temp_path(self, upload_task: UploadTask, temp_path: str) -> FileTask | None:
        """Resolve the FileTask for a staged upload temp path."""
        file_task = upload_task.file_tasks.get(temp_path)
        if file_task is not None:
            return file_task
        for candidate in upload_task.file_tasks.values():
            if candidate.file_path == temp_path:
                return candidate
        return None

    def _is_retryable_local_upload_temp(self, upload_task: UploadTask, temp_path: str) -> bool:
        """True when a staged temp belongs to a failed local RETRYABLE upload.

        Local uploads use the staged path as the file_tasks key and
        FileTask.file_path. When those diverge, this falls back to matching
        FileTask.file_path. Unmapped absolute temps are retained (see
        _should_retain_upload_temp) rather than deleted silently.
        """
        if not os.path.isabs(temp_path):
            return False
        file_task = self._file_task_for_temp_path(upload_task, temp_path)
        if file_task is None or file_task.status != TaskStatus.FAILED:
            return False
        metadata = self._infer_failure_metadata(file_task)
        return bool(metadata and metadata.get("actionable_by") == "RETRYABLE")

    def _should_retain_upload_temp(self, upload_task: UploadTask, temp_path: str) -> bool:
        """Return True when an upload temp should be kept after processing."""
        if self._is_retryable_local_upload_temp(upload_task, temp_path):
            return True
        if (
            os.path.isabs(temp_path)
            and self._file_task_for_temp_path(upload_task, temp_path) is None
        ):
            logger.warning(
                "Upload temp path has no matching file task; retaining staged file",
                temp_path=temp_path,
                task_id=upload_task.task_id,
            )
            return True
        return False

    def _cleanup_upload_temp_files(self, upload_task: UploadTask, *, force: bool = False) -> None:
        """Remove staged upload temp files that are not retryable.

        Keeps temps for failed local uploads classified as RETRYABLE so retry
        can reuse the original source path. Use *force* to delete all temps
        (e.g. user cancelled the task).
        """
        if not getattr(upload_task, "temp_file_paths", None):
            return

        from utils.file_utils import safe_unlink

        retained: list[str] = []
        for temp_path in upload_task.temp_file_paths:
            if not force and self._should_retain_upload_temp(upload_task, temp_path):
                retained.append(temp_path)
                continue
            safe_unlink(temp_path)
            if os.path.exists(temp_path):
                retained.append(temp_path)
                logger.warning(
                    "Failed to clean up temp file after processing",
                    temp_path=temp_path,
                )
            else:
                logger.debug("Cleaned up temp file", temp_path=temp_path)
        upload_task.temp_file_paths = retained

    async def shutdown(self):
        """Cleanup process pool and cancel all background tasks

        Ensures graceful shutdown by:
        1. Cancelling the periodic cleanup task
        2. Cancelling all running background tasks
        3. Waiting for cancellation to complete
        4. Force-cleaning staged upload temps for all tracked tasks
        5. Shutting down the process pool
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
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.warning(
                        "Background task raised exception during shutdown", error=str(result)
                    )

        for user_tasks in self.task_store.values():
            for upload_task in user_tasks.values():
                self._cleanup_upload_temp_files(upload_task, force=True)
