"""Processor behavior for image ingestion when OCR is disabled."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.processors import ConnectorFileProcessor, DocumentFileProcessor, LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

EXPECTED_ERROR = (
    "The file 'scan.PNG' is an image file and cannot be ingested because OCR is disabled."
)


def _disable_ocr(monkeypatch):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(ocr=False, picture_descriptions=False)
        ),
    )


@pytest.mark.asyncio
async def test_document_processor_fails_image_early_when_ocr_disabled(monkeypatch, tmp_path):
    _disable_ocr(monkeypatch)

    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=AsyncMock())
    document_service = MagicMock(session_manager=session_manager)
    document_service.docling_service = MagicMock()

    processor = DocumentFileProcessor(
        document_service=document_service,
        models_service=MagicMock(),
        owner_user_id="user-1",
        jwt_token="jwt",
        session_manager=session_manager,
    )
    processor.check_filename_exists = AsyncMock(return_value=False)
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    image = tmp_path / "scan.PNG"
    image.write_bytes(b"fake image")
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(image), filename="scan.PNG")

    with patch("models.processors.hash_id") as mock_hash_id:
        await processor.process_item(upload_task, str(image), file_task)

    assert file_task.status == TaskStatus.FAILED
    assert file_task.error == EXPECTED_ERROR
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    mock_hash_id.assert_not_called()
    processor.process_document_standard.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_processor_fails_image_early_when_ocr_disabled(monkeypatch):
    _disable_ocr(monkeypatch)

    connector = MagicMock()
    connector.get_file_content = AsyncMock()
    connector_service = MagicMock()
    connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock(connector_type="google_drive")
    connector_service.connection_manager.get_connection = AsyncMock(return_value=connection)

    processor = ConnectorFileProcessor(
        connector_service=connector_service,
        connection_id="conn-id",
        files_to_process=[],
        user_id="user-1",
        jwt_token="jwt",
        document_service=MagicMock(),
        models_service=MagicMock(),
    )

    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path="file-1", filename="scan.PNG")

    await processor.process_item(upload_task, "file-1", file_task)

    assert file_task.status == TaskStatus.FAILED
    assert file_task.error == EXPECTED_ERROR
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    connector.get_file_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_processor_rechecks_loaded_filename_when_ocr_disabled(monkeypatch):
    _disable_ocr(monkeypatch)

    document = SimpleNamespace(
        id="doc-1",
        filename="scan.PNG",
        mimetype="image/png",
        content=b"fake image",
        acl=None,
    )
    connector = MagicMock()
    connector.get_file_content = AsyncMock(return_value=document)
    connector_service = MagicMock()
    connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock(connector_type="google_drive")
    connector_service.connection_manager.get_connection = AsyncMock(return_value=connection)

    processor = ConnectorFileProcessor(
        connector_service=connector_service,
        connection_id="conn-id",
        files_to_process=[],
        user_id="user-1",
        jwt_token="jwt",
        document_service=MagicMock(),
        models_service=MagicMock(),
    )
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path="file-1", filename="file-1")

    with patch("models.processors.hash_id") as mock_hash_id:
        await processor.process_item(upload_task, "file-1", file_task)

    assert file_task.status == TaskStatus.FAILED
    assert file_task.filename == "scan.PNG"
    assert file_task.error == EXPECTED_ERROR
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    connector.get_file_content.assert_awaited_once_with("file-1")
    mock_hash_id.assert_not_called()
    processor.process_document_standard.assert_not_awaited()


@pytest.mark.asyncio
async def test_langflow_processor_fails_image_early_when_ocr_disabled(monkeypatch, tmp_path):
    _disable_ocr(monkeypatch)

    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=AsyncMock())
    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(return_value={"status": "indexed"})

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="user-1",
        jwt_token="jwt",
    )
    processor.check_filename_exists = AsyncMock(return_value=False)

    image = tmp_path / "scan.PNG"
    image.write_bytes(b"fake image")
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(image), filename="scan.PNG")

    await processor.process_item(upload_task, str(image), file_task)

    assert file_task.status == TaskStatus.FAILED
    assert file_task.error == EXPECTED_ERROR
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    langflow_file_service.upload_and_ingest_file.assert_not_awaited()
