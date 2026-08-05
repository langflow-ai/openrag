"""Unit tests for settings handling in DocumentFileProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.processors import DocumentFileProcessor
from models.tasks import FileTask, UploadTask


@pytest.mark.asyncio
async def test_traditional_processor_settings_propagation():
    """Verify that settings like chunkSize, chunkOverlap, and embeddingModel are propagated correctly."""
    mock_doc_service = MagicMock()
    mock_models_service = MagicMock()
    mock_session_manager = MagicMock()

    settings = {
        "chunkSize": 500,
        "chunkOverlap": 50,
        "embeddingModel": "custom-embedding-model",
        "allowed_users": ["user-1"],
        "allowed_groups": ["group-1"],
    }

    processor = DocumentFileProcessor(
        document_service=mock_doc_service,
        models_service=mock_models_service,
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=False,
        session_manager=mock_session_manager,
        settings=settings,
    )

    processor.check_filename_exists = AsyncMock(return_value=False)
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="/tmp/test.txt", filename="test.txt")

    with (
        patch("os.path.getsize", return_value=1234),
        patch("models.processors.hash_id", return_value="dummy-hash"),
    ):
        await processor.process_item(upload_task, "/tmp/test.txt", file_task)

    # Verify standard kwargs passed to process_document_standard
    processor.process_document_standard.assert_called_once()
    kwargs = processor.process_document_standard.call_args.kwargs

    assert kwargs["chunk_size"] == 500
    assert kwargs["chunk_overlap"] == 50
    assert kwargs["embedding_model"] == "custom-embedding-model"
    assert kwargs["acl"] is not None
    assert kwargs["acl"].allowed_users == ["user-1"]
    assert kwargs["acl"].allowed_groups == ["group-1"]


@pytest.mark.asyncio
async def test_traditional_processor_invalid_settings_fallback():
    """Verify that invalid integer settings or empty strings are safely ignored or default handling is used."""
    mock_doc_service = MagicMock()
    mock_models_service = MagicMock()
    mock_session_manager = MagicMock()

    settings = {
        "chunkSize": "invalid-int",
        "chunkOverlap": None,
        "embeddingModel": "   ",  # spaces only
    }

    processor = DocumentFileProcessor(
        document_service=mock_doc_service,
        models_service=mock_models_service,
        owner_user_id="user-123",
        jwt_token="mock-token",
        replace_duplicates=False,
        session_manager=mock_session_manager,
        settings=settings,
    )

    processor.check_filename_exists = AsyncMock(return_value=False)
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    upload_task = UploadTask(task_id="task-123", total_files=1)
    file_task = FileTask(file_path="/tmp/test.txt", filename="test.txt")

    with (
        patch("os.path.getsize", return_value=1234),
        patch("models.processors.hash_id", return_value="dummy-hash"),
    ):
        await processor.process_item(upload_task, "/tmp/test.txt", file_task)

    processor.process_document_standard.assert_called_once()
    kwargs = processor.process_document_standard.call_args.kwargs

    # Should not have passed these to process_document_standard or they fell back to default
    assert "chunk_size" not in kwargs
    assert "chunk_overlap" not in kwargs
    assert "embedding_model" not in kwargs
