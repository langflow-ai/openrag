"""What happens to the loser of an in-flight filename claim when the winner fails.

The duplicate gate decides a losing file's outcome the moment it loses the
claim — before the winning file has ingested anything. If the winner then fails,
nothing was indexed under that name, and the loser's "skipped, it already
exists" is a document the user never got. Worse, SKIPPED is not a retry
candidate (retry_failed_files takes FAILED only), so nothing recovers it.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from models.processors import TaskProcessor
from models.tasks import TaskStatus
from services.task_service import TaskService


class _RacingProcessor(TaskProcessor):
    """Two files heading for one name; the first to claim it can be made to fail.

    Everything below the gate is stubbed — this is about the gate's bookkeeping,
    not about ingestion.
    """

    def __init__(self, *, winner_fails: bool):
        super().__init__()
        self.winner_fails = winner_fails

    async def check_filename_exists(self, filename, opensearch_client, **kwargs):
        # Nothing indexed yet: the window where both files are told the name is free.
        return False

    async def process_item(self, upload_task, item, file_task):
        action = await self.resolve_duplicate_filename(
            file_task.filename,
            AsyncMock(),
            replace=False,
            owner_user_id="user-1",
            claim_holder=self._claim_holder(upload_task, file_task),
        )
        if action == "skip":
            self.mark_duplicate_skipped(upload_task, file_task)
            return

        # Hold the claim long enough for the other file to lose it.
        await asyncio.sleep(0)
        if self.winner_fails:
            # How a processor reports a failure: it owns the status and the
            # counter (TaskService's handler says so explicitly).
            file_task.status = TaskStatus.FAILED
            file_task.error = "The file appears corrupted or invalid and cannot be processed."
            upload_task.failed_files += 1
            return

        file_task.status = TaskStatus.COMPLETED
        upload_task.successful_files += 1


async def _run_pair(winner_fails: bool):
    service = TaskService(document_service=Mock(), ingestion_timeout=5)
    # Force real concurrency: with a single worker the files run one after the
    # other and the second never loses an in-flight claim.
    service._processing_semaphore = asyncio.Semaphore(4)

    processor = _RacingProcessor(winner_fails=winner_fails)
    items = ["/tmp/one/report.pdf", "/tmp/two/report.pdf"]
    task_id = await service.create_custom_task(
        "user-1",
        items,
        processor,
        original_filenames=dict.fromkeys(items, "report.pdf"),
    )
    if service.background_tasks:
        await asyncio.gather(*list(service.background_tasks), return_exceptions=True)

    upload_task = service.task_store["user-1"][task_id]
    return service, task_id, upload_task


@pytest.mark.asyncio
async def test_loser_is_failed_when_the_winner_fails():
    """Nothing reached the index, so neither file may be reported as successful."""
    _, _, upload_task = await _run_pair(winner_fails=True)

    statuses = [t.status for t in upload_task.file_tasks.values()]
    assert statuses == [TaskStatus.FAILED, TaskStatus.FAILED]
    assert upload_task.successful_files == 0
    assert upload_task.failed_files == 2


@pytest.mark.asyncio
async def test_a_failed_winner_leaves_the_loser_retryable():
    """retry_failed_files only considers FAILED, so the loser has to land there
    to be recoverable — and the retry re-runs the gate, which resolves correctly
    either way."""
    service, task_id, upload_task = await _run_pair(winner_fails=True)

    loser = upload_task.file_tasks["/tmp/two/report.pdf"]
    assert loser.status is TaskStatus.FAILED
    metadata = service._infer_failure_metadata(loser)
    assert metadata["actionable_by"] == "RETRYABLE"


@pytest.mark.asyncio
async def test_loser_stays_a_skipped_duplicate_when_the_winner_succeeds():
    """The ordinary case is untouched: one document indexed, the other skipped as
    a duplicate and counted successful."""
    _, _, upload_task = await _run_pair(winner_fails=False)

    statuses = {t.status for t in upload_task.file_tasks.values()}
    assert statuses == {TaskStatus.COMPLETED, TaskStatus.SKIPPED}
    assert upload_task.successful_files == 2
    assert upload_task.failed_files == 0

    skipped = next(t for t in upload_task.file_tasks.values() if t.status is TaskStatus.SKIPPED)
    assert skipped.result["reason"] == "duplicate_filename"
