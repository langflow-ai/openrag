from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import DocumentFileProcessor, LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from services.local_source_service import find_local_source, get_indexed_documents_path
from utils.hash_utils import hash_id


@pytest.fixture
def archive_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_PUBLIC_URL", raising=False)
    return tmp_path


def _document_processor() -> DocumentFileProcessor:
    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        session_manager=MagicMock(),
        archive_sources=True,
    )
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    return processor


@pytest.mark.asyncio
async def test_traditional_processor_archives_successful_original(archive_environment):
    source = archive_environment / "inbox" / "report.txt"
    source.parent.mkdir()
    source.write_text("evidence")
    document_id = hash_id(source)

    processor = _document_processor()
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(source), filename="report.txt")

    await processor.process_item(upload_task, str(source), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert not source.exists()
    kwargs = processor.process_document_standard.await_args.kwargs
    source_id = kwargs["source_url"].rsplit("/", 1)[-1]
    assert source_id.startswith(f"{document_id}.")
    assert find_local_source(source_id) is not None
    assert kwargs["file_path"] == str(find_local_source(source_id))


@pytest.mark.asyncio
async def test_traditional_processor_rolls_source_back_on_failure(archive_environment):
    source = archive_environment / "inbox" / "report.txt"
    source.parent.mkdir()
    source.write_text("evidence")
    document_id = hash_id(source)

    processor = _document_processor()
    processor.process_document_standard = AsyncMock(
        return_value={"status": "error", "error": "index failed"}
    )
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(source), filename="report.txt")

    await processor.process_item(upload_task, str(source), file_task)

    assert file_task.status == TaskStatus.FAILED
    assert source.read_text() == "evidence"
    assert not list(get_indexed_documents_path().glob(f"{document_id}.*"))


@pytest.mark.asyncio
async def test_traditional_processor_preserves_remote_source_without_local_archive(
    archive_environment,
):
    source = archive_environment / "inbox" / "report.txt"
    source.parent.mkdir()
    source.write_text("evidence")
    remote_url = "https://files.example.com/report.txt"

    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        session_manager=MagicMock(),
        source_urls={str(source): remote_url},
        archive_sources=False,
    )
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(source), filename="report.txt")

    await processor.process_item(upload_task, str(source), file_task)

    assert source.exists()
    assert processor.process_document_standard.await_args.kwargs["source_url"] == remote_url
    assert not get_indexed_documents_path().exists()


@pytest.mark.asyncio
async def test_traditional_processor_does_not_orphan_archive_when_hash_is_unchanged(
    archive_environment,
):
    source = archive_environment / "inbox" / "report.txt"
    source.parent.mkdir()
    source.write_text("evidence")

    processor = _document_processor()
    processor.process_document_standard = AsyncMock(return_value={"status": "unchanged"})
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(source), filename="report.txt")

    await processor.process_item(upload_task, str(source), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert source.read_text() == "evidence"
    assert not list(get_indexed_documents_path().rglob("*"))


@pytest.mark.asyncio
async def test_langflow_processor_archives_manual_upload(archive_environment):
    source = archive_environment / "inbox" / "message.eml"
    source.parent.mkdir()
    source.write_bytes(b"From: sender@example.com\n\nHello")
    document_id = hash_id(source)

    service = MagicMock()
    service.upload_and_ingest_file = AsyncMock(return_value={"status": "indexed"})
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = AsyncMock()
    processor = LangflowFileProcessor(
        langflow_file_service=service,
        session_manager=session_manager,
        archive_sources=True,
    )
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    processor.check_filename_exists = AsyncMock(return_value=True)
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=str(source), filename="message.eml")

    await processor.process_item(upload_task, str(source), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert not source.exists()
    kwargs = service.upload_and_ingest_file.await_args.kwargs
    source_id = kwargs["source_url"].rsplit("/", 1)[-1]
    assert source_id.startswith(f"{document_id}.")
    assert find_local_source(source_id) is not None
