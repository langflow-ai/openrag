"""Regression tests for content-duplicate detection in LangflowFileProcessor.

When a user uploads a byte-identical file under a different name, the filename
guard (resolve_duplicate_filename) does not fire — the names differ.  The
processor must fall through to a content-hash check (check_document_exists)
and surface the result as SKIPPED with reason=duplicate_content, mirroring the
behaviour of the connector and traditional paths.

Relates to issue #2388.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import DUPLICATE_CONTENT_WARNING, LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_processor() -> LangflowFileProcessor:
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=AsyncMock())

    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )

    return LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="user-1",
        jwt_token="Bearer token",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_langflow_processor_skips_on_content_duplicate(tmp_path):
    """Re-uploading identical content under a new filename must be SKIPPED with
    a user-visible warning, not silently overwritten."""
    processor = _build_processor()

    # Filename check: no existing document with this name → proceed.
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    # Content check: identical bytes already in the index.
    processor.check_document_exists = AsyncMock(return_value=True)

    item = tmp_path / "leave-policy-COPY.pdf"
    item.write_bytes(b"%PDF-1.4 identical content")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "leave-policy-COPY.pdf"
    upload_task = UploadTask(task_id="task-1", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.error is None
    assert file_task.result == {
        "status": "skipped",
        "reason": "duplicate_content",
        "warning": DUPLICATE_CONTENT_WARNING,
        "document_id": file_task.document_id,
    }
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 1
    # Expensive work (Docling + Langflow) must not run for a content duplicate.
    processor.langflow_file_service.upload_and_ingest_file.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_processor_content_check_uses_file_hash(tmp_path):
    """check_document_exists must be called with the content hash of the file,
    so two identical files produce the same hash regardless of their names."""
    from utils.hash_utils import hash_id

    processor = _build_processor()
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    processor.check_document_exists = AsyncMock(return_value=True)

    content = b"%PDF-1.4 hash-me"
    item = tmp_path / "copy.pdf"
    item.write_bytes(content)

    file_task = FileTask(file_path=str(item))
    file_task.filename = "copy.pdf"
    upload_task = UploadTask(task_id="task-2", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    expected_hash = hash_id(str(item))
    processor.check_document_exists.assert_awaited_once()
    actual_hash_arg = processor.check_document_exists.await_args.args[0]
    assert actual_hash_arg == expected_hash
    assert file_task.document_id == expected_hash


@pytest.mark.asyncio
async def test_langflow_processor_new_content_proceeds(tmp_path):
    """When no content duplicate exists, processing must continue normally —
    the guard must be transparent for new files."""
    processor = _build_processor()
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    # Content not yet indexed.
    processor.check_document_exists = AsyncMock(return_value=False)
    # Post-ingest verification: file visible after ingest.
    processor.check_filename_exists = AsyncMock(return_value=True)

    item = tmp_path / "new-file.pdf"
    item.write_bytes(b"%PDF-1.4 brand new")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "new-file.pdf"
    upload_task = UploadTask(task_id="task-3", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
    processor.langflow_file_service.upload_and_ingest_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_processor_filename_duplicate_still_wins(tmp_path):
    """The filename guard fires first; if it skips, the content guard is never
    reached (and upload_and_ingest_file is still not called)."""
    processor = _build_processor()
    # Filename guard skips.
    processor.resolve_duplicate_filename = AsyncMock(return_value="skip")
    processor.check_document_exists = AsyncMock(return_value=True)

    item = tmp_path / "report.pdf"
    item.write_bytes(b"%PDF-1.4 something")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "report.pdf"
    upload_task = UploadTask(task_id="task-4", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.result["reason"] == "duplicate_filename"
    # Content check must never run when the filename guard already skipped.
    processor.check_document_exists.assert_not_called()
    processor.langflow_file_service.upload_and_ingest_file.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_processor_replace_same_name_same_content_proceeds(tmp_path):
    """replace_duplicates=True with a same-name file whose content hash already
    exists must NOT trigger the content-duplicate skip.  The old chunks were
    already deleted by resolve_duplicate_filename; bailing out here would leave
    the index empty.  Ingest must proceed to re-index the document."""
    processor = _build_processor()
    # Filename guard deleted the old chunks and returned "replaced".
    processor.resolve_duplicate_filename = AsyncMock(return_value="replaced")
    # Hash matches the just-deleted document — must not short-circuit.
    processor.check_document_exists = AsyncMock(return_value=True)
    # Post-ingest verification: file visible after ingest.
    processor.check_filename_exists = AsyncMock(return_value=True)

    item = tmp_path / "report.pdf"
    item.write_bytes(b"%PDF-1.4 same bytes")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "report.pdf"
    upload_task = UploadTask(task_id="task-5", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    # Content guard must not have fired — ingest must have run.
    processor.langflow_file_service.upload_and_ingest_file.assert_awaited_once()
    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
    assert upload_task.failed_files == 0


@pytest.mark.asyncio
async def test_langflow_processor_concurrent_same_hash_only_one_proceeds(tmp_path):
    """Two concurrent uploads with identical content must result in exactly one
    Docling/Langflow submission.  The second coroutine sees the hash already
    present (as it would after the first ingest completes) and skips.

    This is a best-effort in-process guard: check_document_exists is called
    before upload_and_ingest_file, so the race window is limited to the gap
    between the check and the write.  A full atomic claim would require a
    distributed lock (tracked separately); this test verifies the guard position
    is correct and that the skip path is exercised under concurrency."""
    import asyncio

    call_count = 0

    async def fake_upload(**kwargs):
        nonlocal call_count
        call_count += 1
        return {"status": "indexed", "id": "hash-concurrent"}

    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=AsyncMock())

    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = fake_upload

    item = tmp_path / "concurrent.pdf"
    item.write_bytes(b"%PDF-1.4 concurrent content")

    # Simulate: first call sees hash absent, second sees it present (post-ingest).
    exists_results = [False, True]

    async def fake_check_document_exists(file_hash, client):
        return exists_results.pop(0)

    async def run_one():
        processor = LangflowFileProcessor(
            langflow_file_service=langflow_file_service,
            session_manager=session_manager,
            owner_user_id="user-1",
            jwt_token="Bearer token",
        )
        processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
        processor.check_document_exists = fake_check_document_exists
        processor.check_filename_exists = AsyncMock(return_value=True)
        ft = FileTask(file_path=str(item))
        ft.filename = "concurrent.pdf"
        ut = UploadTask(task_id="task-concurrent", total_files=2)
        await processor.process_item(ut, str(item), ft)
        return ft

    results = await asyncio.gather(run_one(), run_one())

    statuses = {r.status for r in results}
    assert call_count == 1, "upload_and_ingest_file must be called exactly once"
    assert TaskStatus.COMPLETED in statuses
    assert TaskStatus.SKIPPED in statuses
