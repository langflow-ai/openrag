from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.tasks import FileTask, TaskStatus, UploadTask
from models.url import UrlProcessor
from services.task_service import TaskService


@pytest.mark.asyncio
async def test_url_processor_retains_successful_processing_result(tmp_path):
    materialized_file = tmp_path / "docs.txt"
    materialized_file.write_text("documentation")
    result = {"status": "indexed", "id": "document-id"}

    document_processor = MagicMock()
    document_processor.process_document_standard = AsyncMock(return_value=result)
    processor = UrlProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        docs_url="https://docs.example.test",
        crawl_depth=1,
    )
    upload_task = UploadTask(task_id="url-task", total_files=1)
    file_task = FileTask(file_path=processor.docs_url)

    with (
        patch(
            "utils.url_content_fetcher.materialize_url_as_text_file",
            new=AsyncMock(return_value=(str(materialized_file), "OpenRAG docs")),
        ),
        patch("models.processors.DocumentFileProcessor", return_value=document_processor),
    ):
        await processor.process_item(upload_task, processor.docs_url, file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert file_task.result == result
    assert upload_task.successful_files == 1
    assert upload_task.failed_files == 0


@pytest.mark.asyncio
async def test_url_processor_marks_structured_processing_error_as_failed(tmp_path):
    materialized_file = tmp_path / "docs.txt"
    materialized_file.write_text("documentation")

    document_processor = MagicMock()
    document_processor.process_document_standard = AsyncMock(
        return_value={"status": "error", "error": "No text content could be extracted"}
    )
    processor = UrlProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        docs_url="https://docs.example.test",
        crawl_depth=1,
    )
    upload_task = UploadTask(task_id="url-task", total_files=1)
    file_task = FileTask(file_path=processor.docs_url)

    with (
        patch(
            "utils.url_content_fetcher.materialize_url_as_text_file",
            new=AsyncMock(return_value=(str(materialized_file), "OpenRAG docs")),
        ),
        patch("models.processors.DocumentFileProcessor", return_value=document_processor),
    ):
        await processor.process_item(upload_task, processor.docs_url, file_task)

    assert file_task.status == TaskStatus.FAILED
    assert file_task.error == "No text content could be extracted"
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    assert not materialized_file.exists()


@pytest.mark.asyncio
async def test_create_url_upload_task_wires_url_processor_context():
    document_service = MagicMock()
    models_service = MagicMock()
    task_service = TaskService(
        document_service=document_service,
        models_service=models_service,
    )
    task_service.create_custom_task = AsyncMock(return_value="url-task")

    task_id = await task_service.create_url_upload_task(
        owner_user_id="owner-id",
        docs_url="https://docs.example.test",
        crawl_depth=2,
        jwt_token="Bearer token",
        owner_name="Owner Name",
        owner_email="owner@example.test",
        connector_type="openrag_docs",
        is_sample_data=True,
    )

    assert task_id == "url-task"
    owner_user_id, items, processor = task_service.create_custom_task.await_args.args
    assert owner_user_id == "owner-id"
    assert items == ["https://docs.example.test"]
    assert isinstance(processor, UrlProcessor)
    assert processor.document_service is document_service
    assert processor.models_service is models_service
    assert processor.owner_user_id == "owner-id"
    assert processor.docs_url == "https://docs.example.test"
    assert processor.crawl_depth == 2
    assert processor.jwt_token == "Bearer token"
    assert processor.owner_name == "Owner Name"
    assert processor.owner_email == "owner@example.test"
    assert processor.connector_type == "openrag_docs"
    assert processor.is_sample_data is True
