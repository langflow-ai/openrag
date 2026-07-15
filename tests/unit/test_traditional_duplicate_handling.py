"""Unit tests for the unified duplicate-filename gate across processors.

All processors resolve a filename duplicate the same way via
``TaskProcessor.resolve_duplicate_filename``: with ``replace_duplicates=False``
the file is SKIPPED (counted successful, with a warning); with
``replace_duplicates=True`` the existing document is deleted and ingestion
proceeds.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.processors import (
    DUPLICATE_FILENAME_WARNING,
    DocumentFileProcessor,
    LangflowFileProcessor,
    S3FileProcessor,
)
from models.tasks import FileTask, TaskStatus, UploadTask

DUPLICATE_SKIPPED_RESULT = {
    "status": "skipped",
    "reason": "duplicate_filename",
    "warning": DUPLICATE_FILENAME_WARNING,
}


def _assert_duplicate_skipped(upload_task: UploadTask, file_task: FileTask) -> None:
    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.error is None
    assert file_task.result == DUPLICATE_SKIPPED_RESULT
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 1


@pytest.mark.asyncio
async def test_traditional_processor_duplicate_exists_no_replace():
    """A duplicate with replace_duplicates=False is skipped, not failed."""
    mock_doc_service = MagicMock()
    mock_models_service = MagicMock()
    mock_session_manager = MagicMock()

    processor = DocumentFileProcessor(
        document_service=mock_doc_service,
        models_service=mock_models_service,
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=False,
        session_manager=mock_session_manager,
    )

    # Assert that session_manager was set correctly on the processor
    assert processor.session_manager == mock_session_manager

    # Mock base class methods directly on the instance to ensure perfect isolation
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="/tmp/test.txt", filename="test.txt")

    await processor.process_item(upload_task, "/tmp/test.txt", file_task)

    _assert_duplicate_skipped(upload_task, file_task)

    processor.check_filename_exists.assert_called_once()
    processor.delete_document_by_filename.assert_not_called()
    mock_session_manager.get_user_opensearch_client.assert_called_once_with(
        "user-123", "mock-token"
    )


@pytest.mark.asyncio
async def test_traditional_processor_duplicate_exists_with_replace():
    """Verify that if a duplicate file exists and replace_duplicates is True, the old document is deleted and ingestion succeeds."""
    mock_doc_service = MagicMock()
    mock_models_service = MagicMock()
    mock_session_manager = MagicMock()

    processor = DocumentFileProcessor(
        document_service=mock_doc_service,
        models_service=mock_models_service,
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=True,
        session_manager=mock_session_manager,
    )

    # Assert that session_manager was set correctly on the processor
    assert processor.session_manager == mock_session_manager

    # Mock base class methods directly on the instance to ensure perfect isolation
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="/tmp/test.txt", filename="test.txt")

    with (
        patch("os.path.getsize", return_value=1234),
        patch("models.processors.hash_id", return_value="dummy-hash"),
    ):
        await processor.process_item(upload_task, "/tmp/test.txt", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert file_task.error is None
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 1

    processor.check_filename_exists.assert_called_once()
    processor.delete_document_by_filename.assert_called_once()
    # The delete must be owner-scoped so it actually removes the old chunks.
    delete_call = processor.delete_document_by_filename.call_args
    assert delete_call.kwargs["owner_user_id"] == "user-123"
    processor.process_document_standard.assert_called_once()
    mock_session_manager.get_user_opensearch_client.assert_called_once_with(
        "user-123", "mock-token"
    )


@pytest.mark.asyncio
async def test_langflow_processor_duplicate_exists_no_replace():
    """LangflowFileProcessor skips duplicates with the same uniform payload."""
    mock_session_manager = MagicMock()
    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock()

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=mock_session_manager,
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=False,
    )
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="/tmp/test.txt", filename="test.txt")

    await processor.process_item(upload_task, "/tmp/test.txt", file_task)

    _assert_duplicate_skipped(upload_task, file_task)
    processor.delete_document_by_filename.assert_not_called()
    langflow_file_service.upload_and_ingest_file.assert_not_called()


def _build_s3_processor(replace_duplicates: bool) -> S3FileProcessor:
    document_service = MagicMock()
    document_service.session_manager = MagicMock()
    processor = S3FileProcessor(
        document_service,
        bucket="test-bucket",
        s3_client=MagicMock(),
        owner_user_id="user-123",
        jwt_token="mock-token",
        models_service=MagicMock(),
        docling_service=MagicMock(),
        replace_duplicates=replace_duplicates,
    )
    return processor


@pytest.mark.asyncio
async def test_s3_processor_duplicate_exists_no_replace():
    """S3FileProcessor now has the same duplicate gate: same-key duplicates
    are skipped before the object is even downloaded."""
    processor = _build_s3_processor(replace_duplicates=False)
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="docs/report.pdf", filename="docs/report.pdf")

    await processor.process_item(upload_task, "docs/report.pdf", file_task)

    _assert_duplicate_skipped(upload_task, file_task)
    processor.delete_document_by_filename.assert_not_called()
    processor.s3_client.download_fileobj.assert_not_called()


@pytest.mark.asyncio
async def test_s3_processor_duplicate_exists_with_replace(tmp_path):
    """With replace_duplicates=True the old document is deleted and the object
    is downloaded and processed."""
    processor = _build_s3_processor(replace_duplicates=True)
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()
    processor.process_document_standard = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )
    processor.s3_client.head_object = MagicMock(return_value={"ContentLength": 10})

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="docs/report.pdf", filename="docs/report.pdf")

    with patch("models.processors.hash_id", return_value="dummy-hash"):
        await processor.process_item(upload_task, "docs/report.pdf", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
    processor.delete_document_by_filename.assert_called_once()
    assert processor.delete_document_by_filename.call_args.kwargs["owner_user_id"] == "user-123"
    processor.s3_client.download_fileobj.assert_called_once()
    processor.process_document_standard.assert_awaited_once()


@pytest.mark.asyncio
async def test_s3_processor_no_duplicate_proceeds():
    """No duplicate: the gate is a no-op and processing continues."""
    processor = _build_s3_processor(replace_duplicates=False)
    processor.check_filename_exists = AsyncMock(return_value=False)
    processor.delete_document_by_filename = AsyncMock()
    processor.process_document_standard = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )
    processor.s3_client.head_object = MagicMock(return_value={"ContentLength": 10})

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="docs/report.pdf", filename="docs/report.pdf")

    with patch("models.processors.hash_id", return_value="dummy-hash"):
        await processor.process_item(upload_task, "docs/report.pdf", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    processor.delete_document_by_filename.assert_not_called()
    processor.process_document_standard.assert_awaited_once()
