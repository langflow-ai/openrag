"""Two files heading for the same indexed filename, ingested at once.

Files inside a task run concurrently under TaskService's worker semaphore, and
the duplicate gate's question — "is this name already indexed?" — is answered
by OpenSearch, which cannot see a file that has not been written yet. Two files
named report.pdf (different folders in an upload, different keys under one
bucket prefix, a Drive selection spanning folders) therefore both passed the
gate, and their chunk ids are content-derived, so neither overwrote the other:
one filename ended up holding two documents' chunks. With replace_duplicates on
— the default for uploads — the later file deleted the earlier one's chunks
instead, while the earlier file's task still reported success.

The in-flight claim makes the second file resolve as an ordinary duplicate.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.processors import DUPLICATE_FILENAME_WARNING, DocumentFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask


def _processor(replace_duplicates: bool) -> DocumentFileProcessor:
    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=replace_duplicates,
        session_manager=MagicMock(),
    )
    # The index is empty as far as either file can tell: this is the window
    # where both of them are told the name is free.
    processor.check_filename_exists = AsyncMock(return_value=False)
    processor.delete_document_by_filename = AsyncMock(return_value=1)
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})
    return processor


async def _ingest_both_at_once(processor, upload_task, file_tasks):
    with (
        patch("os.path.getsize", return_value=1234),
        patch("models.processors.hash_id", side_effect=lambda path: f"hash-{path}"),
    ):
        await asyncio.gather(
            *(
                processor.process_item(upload_task, file_task.file_path, file_task)
                for file_task in file_tasks
            )
        )


@pytest.mark.asyncio
async def test_only_one_of_two_same_named_files_is_ingested():
    processor = _processor(replace_duplicates=False)
    upload_task = UploadTask(task_id="task-123", total_files=2)
    first = FileTask(file_path="/tmp/one/report.pdf", filename="report.pdf")
    second = FileTask(file_path="/tmp/two/report.pdf", filename="report.pdf")

    await _ingest_both_at_once(processor, upload_task, [first, second])

    assert {first.status, second.status} == {TaskStatus.COMPLETED, TaskStatus.SKIPPED}
    # One document indexed, not two under one name.
    processor.process_document_standard.assert_called_once()

    skipped = first if first.status is TaskStatus.SKIPPED else second
    assert skipped.result["reason"] == "duplicate_filename"
    assert skipped.result["warning"] == DUPLICATE_FILENAME_WARNING
    assert skipped.error is None
    # A declined duplicate is a chosen outcome, not a failure.
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 2


@pytest.mark.asyncio
async def test_replace_duplicates_does_not_let_the_second_file_delete_the_first():
    """With replace on, the loser used to delete the winner's freshly written
    chunks and index itself over them."""
    processor = _processor(replace_duplicates=True)
    upload_task = UploadTask(task_id="task-123", total_files=2)
    first = FileTask(file_path="/tmp/one/report.pdf", filename="report.pdf")
    second = FileTask(file_path="/tmp/two/report.pdf", filename="report.pdf")

    await _ingest_both_at_once(processor, upload_task, [first, second])

    processor.process_document_standard.assert_called_once()
    processor.delete_document_by_filename.assert_not_called()


@pytest.mark.asyncio
async def test_aliases_of_one_name_also_resolve_to_one_file():
    """notes.txt is indexed as notes.md by the Langflow path, so the pair is one
    name for duplicate purposes."""
    processor = _processor(replace_duplicates=False)
    upload_task = UploadTask(task_id="task-123", total_files=2)
    txt = FileTask(file_path="/tmp/notes.txt", filename="notes.txt")
    md = FileTask(file_path="/tmp/notes.md", filename="notes.md")

    await _ingest_both_at_once(processor, upload_task, [txt, md])

    processor.process_document_standard.assert_called_once()
    assert {txt.status, md.status} == {TaskStatus.COMPLETED, TaskStatus.SKIPPED}


@pytest.mark.asyncio
async def test_differently_named_files_are_both_ingested():
    """The claim must not serialize an ordinary batch."""
    processor = _processor(replace_duplicates=False)
    upload_task = UploadTask(task_id="task-123", total_files=2)
    first = FileTask(file_path="/tmp/a.pdf", filename="a.pdf")
    second = FileTask(file_path="/tmp/b.pdf", filename="b.pdf")

    await _ingest_both_at_once(processor, upload_task, [first, second])

    assert first.status is TaskStatus.COMPLETED
    assert second.status is TaskStatus.COMPLETED
    assert processor.process_document_standard.await_count == 2
