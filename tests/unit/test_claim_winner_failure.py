"""What happens to the loser of an in-flight filename claim when the winner fails.

The duplicate gate decides a losing file's outcome the moment it loses the
claim — before the winning file has ingested anything. If the winner then fails,
nothing was indexed under that name, and the loser's "skipped, it already
exists" is a document the user never got. Worse, SKIPPED is not a retry
candidate (retry_failed_files takes FAILED only), so nothing recovers it.
"""

import asyncio
import os
from unittest.mock import AsyncMock, Mock

import pytest

from models.processors import DUPLICATE_SKIP_ACTIONS, TaskProcessor
from models.tasks import TaskStatus
from services.task_service import TaskService
from utils.filename_claims import INFLIGHT_CLAIM_WINNER_FAILED_ERROR


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
        if action in DUPLICATE_SKIP_ACTIONS:
            # Both skips finish a file the same way; only the reconcile in
            # ConnectorFileProcessor tells them apart.
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


class _HeldClaimProcessor(TaskProcessor):
    """Claims the name, then holds it until released — so a second task can lose
    the race while this one is still in flight."""

    def __init__(self, *, claimed: asyncio.Event, may_finish: asyncio.Event):
        super().__init__()
        self.claimed = claimed
        self.may_finish = may_finish

    async def check_filename_exists(self, filename, opensearch_client, **kwargs):
        return False

    async def process_item(self, upload_task, item, file_task):
        action = await self.resolve_duplicate_filename(
            file_task.filename,
            AsyncMock(),
            replace=False,
            owner_user_id="user-1",
            claim_holder=self._claim_holder(upload_task, file_task),
        )
        assert action == "proceed"
        self.claimed.set()
        await self.may_finish.wait()
        file_task.status = TaskStatus.FAILED
        file_task.error = "The file appears corrupted or invalid and cannot be processed."
        upload_task.failed_files += 1


class _LosingProcessor(TaskProcessor):
    async def check_filename_exists(self, filename, opensearch_client, **kwargs):
        return False

    async def process_item(self, upload_task, item, file_task):
        action = await self.resolve_duplicate_filename(
            file_task.filename,
            AsyncMock(),
            replace=False,
            owner_user_id="user-1",
            claim_holder=self._claim_holder(upload_task, file_task),
        )
        assert action in DUPLICATE_SKIP_ACTIONS
        self.mark_duplicate_skipped(upload_task, file_task)


@pytest.mark.asyncio
async def test_a_loser_in_another_task_is_recovered_too():
    """Claims are keyed by name and ownership, not by task, so the file that
    loses can belong to a different task — two uploads in flight, or an upload
    racing a connector sync. It has to be recovered there, in its own task."""
    service = TaskService(document_service=Mock(), ingestion_timeout=5)
    service._processing_semaphore = asyncio.Semaphore(4)

    claimed = asyncio.Event()
    may_finish = asyncio.Event()

    winner_task_id = await service.create_custom_task(
        "user-1",
        ["/tmp/winner/report.pdf"],
        _HeldClaimProcessor(claimed=claimed, may_finish=may_finish),
        original_filenames={"/tmp/winner/report.pdf": "report.pdf"},
    )
    await asyncio.wait_for(claimed.wait(), timeout=5)

    # A separate task, started while the first still holds the name.
    loser_task_id = await service.create_custom_task(
        "user-1",
        ["/tmp/loser/report.pdf"],
        _LosingProcessor(),
        original_filenames={"/tmp/loser/report.pdf": "report.pdf"},
    )
    loser_task = service.task_store["user-1"][loser_task_id]
    while loser_task.processed_files < 1:
        await asyncio.sleep(0)

    # The loser is already finalized as a successful skip before the winner fails.
    loser_file = loser_task.file_tasks["/tmp/loser/report.pdf"]
    assert loser_file.status is TaskStatus.SKIPPED
    assert loser_task.successful_files == 1

    may_finish.set()
    await asyncio.gather(*list(service.background_tasks), return_exceptions=True)

    assert (
        service.task_store["user-1"][winner_task_id].file_tasks["/tmp/winner/report.pdf"].status
        is TaskStatus.FAILED
    )

    assert loser_file.status is TaskStatus.FAILED
    assert loser_file.error == INFLIGHT_CLAIM_WINNER_FAILED_ERROR
    assert loser_task.successful_files == 0
    assert loser_task.failed_files == 1
    # The loser's task finished before the reversal; its accounting stays whole.
    assert loser_task.processed_files == loser_task.total_files


@pytest.mark.asyncio
async def test_a_cross_task_loser_keeps_its_staged_file(tmp_path):
    """The loser's task finishes — and cleans up — while the winner is still in
    flight. The staged source has to survive that, or the FAILED state the
    reversal produces is one retry cannot act on: retry_failed_files rejects a
    file whose source is gone as "source_file_missing".
    """
    service = TaskService(document_service=Mock(), ingestion_timeout=5)
    service._processing_semaphore = asyncio.Semaphore(4)

    claimed = asyncio.Event()
    may_finish = asyncio.Event()

    winner_path = tmp_path / "winner-report.pdf"
    winner_path.write_bytes(b"%PDF-winner")
    loser_path = tmp_path / "loser-report.pdf"
    loser_path.write_bytes(b"%PDF-loser")

    await service.create_custom_task(
        "user-1",
        [str(winner_path)],
        _HeldClaimProcessor(claimed=claimed, may_finish=may_finish),
        original_filenames={str(winner_path): "report.pdf"},
        temp_file_paths=[str(winner_path)],
    )
    await asyncio.wait_for(claimed.wait(), timeout=5)

    loser_task_id = await service.create_custom_task(
        "user-1",
        [str(loser_path)],
        _LosingProcessor(),
        original_filenames={str(loser_path): "report.pdf"},
        temp_file_paths=[str(loser_path)],
    )
    loser_task = service.task_store["user-1"][loser_task_id]
    while loser_task.status != TaskStatus.COMPLETED:
        await asyncio.sleep(0)

    # Its task has finished and run cleanup, with the outcome still unsettled.
    assert loser_path.exists(), "staged source deleted before the winner resolved"

    may_finish.set()
    await asyncio.gather(*list(service.background_tasks), return_exceptions=True)

    loser_file = loser_task.file_tasks[str(loser_path)]
    assert loser_file.status is TaskStatus.FAILED
    assert loser_path.exists(), "retry has nothing to read"
    # What retry checks before re-queueing.
    assert os.path.exists(loser_file.file_path)


@pytest.mark.asyncio
async def test_an_ordinary_duplicate_skip_still_cleans_up(tmp_path):
    """Retention is only for the unsettled case — a file skipped against a
    document that is already indexed keeps today's cleanup."""
    service = TaskService(document_service=Mock(), ingestion_timeout=5)

    staged = tmp_path / "report.pdf"
    staged.write_bytes(b"%PDF-")

    class _AlreadyIndexedProcessor(TaskProcessor):
        async def check_filename_exists(self, filename, opensearch_client, **kwargs):
            return True

        async def process_item(self, upload_task, item, file_task):
            action = await self.resolve_duplicate_filename(
                file_task.filename,
                AsyncMock(),
                replace=False,
                owner_user_id="user-1",
                claim_holder=self._claim_holder(upload_task, file_task),
            )
            assert action in DUPLICATE_SKIP_ACTIONS
            self.mark_duplicate_skipped(upload_task, file_task)

    await service.create_custom_task(
        "user-1",
        [str(staged)],
        _AlreadyIndexedProcessor(),
        original_filenames={str(staged): "report.pdf"},
        temp_file_paths=[str(staged)],
    )
    await asyncio.gather(*list(service.background_tasks), return_exceptions=True)

    assert not staged.exists()
