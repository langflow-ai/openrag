"""Unit tests for duplicate filename handling in DocumentFileProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.processors import DocumentFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask


@pytest.mark.asyncio
async def test_traditional_processor_duplicate_exists_no_replace():
    """Verify that if a duplicate file exists and replace_duplicates is False, processing fails."""
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

    assert file_task.status == TaskStatus.FAILED
    assert "already exists" in file_task.error
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0

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
    processor.process_document_standard.assert_called_once()
    mock_session_manager.get_user_opensearch_client.assert_called_once_with(
        "user-123", "mock-token"
    )
