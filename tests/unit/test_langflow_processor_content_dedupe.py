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
