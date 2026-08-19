from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import DocumentFileProcessor, LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from services.local_source_service import find_local_source, get_indexed_documents_path
from utils.hash_utils import hash_id


@pytest.fixture
def archive_environment(tmp_path, monkeypatch):
    """Configure isolated local source paths for processor tests."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_PUBLIC_URL", raising=False)
    return tmp_path


def _document_processor() -> DocumentFileProcessor:
    """Build a document processor configured to archive original sources."""
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
    """Commit an original source after successful traditional ingestion."""
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
    """Restore the original source after failed traditional ingestion."""
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
    """Preserve remote source metadata when local archiving is disabled."""
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
async def test_path_processor_deletes_source_only_after_successful_index(archive_environment):
    """Consume a path-ingested source only after it was indexed successfully."""
    successful_source = archive_environment / "inbox" / "indexed.txt"
    failed_source = archive_environment / "inbox" / "failed.txt"
    successful_source.parent.mkdir()
    successful_source.write_text("indexed")
    failed_source.write_text("failed")

    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        session_manager=MagicMock(),
        delete_source_after_success=True,
    )
    processor.resolve_duplicate_filename = AsyncMock(return_value="proceed")
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    await processor.process_item(
        UploadTask(task_id="task-success", total_files=1),
        str(successful_source),
        FileTask(file_path=str(successful_source), filename=successful_source.name),
    )

    processor.process_document_standard = AsyncMock(
        return_value={"status": "error", "error": "index failed"}
    )
    await processor.process_item(
        UploadTask(task_id="task-failure", total_files=1),
        str(failed_source),
        FileTask(file_path=str(failed_source), filename=failed_source.name),
    )

    assert not successful_source.exists()
    assert failed_source.read_text() == "failed"


@pytest.mark.asyncio
async def test_path_processor_uses_content_hash_instead_of_filename(archive_environment):
    """Ingest a same-name file and consume content reported as unchanged."""
    same_name_source = archive_environment / "inbox" / "same-name.txt"
    unchanged_source = archive_environment / "inbox" / "unchanged.txt"
    same_name_source.parent.mkdir()
    same_name_source.write_text("new content with an existing filename")
    unchanged_source.write_text("unchanged")

    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        session_manager=MagicMock(),
        delete_source_after_success=True,
    )
    processor.resolve_duplicate_filename = AsyncMock(return_value="skip")
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})
    same_name_task = FileTask(file_path=str(same_name_source), filename=same_name_source.name)

    await processor.process_item(
        UploadTask(task_id="task-same-name", total_files=1),
        str(same_name_source),
        same_name_task,
    )

    assert same_name_task.status == TaskStatus.COMPLETED
    assert not same_name_source.exists()
    processor.resolve_duplicate_filename.assert_not_awaited()
    indexed_kwargs = processor.process_document_standard.await_args.kwargs
    assert indexed_kwargs["file_hash"] == same_name_task.document_id

    processor.archive_sources = True
    processor.process_document_standard = AsyncMock(return_value={"status": "unchanged"})
    unchanged_task = FileTask(file_path=str(unchanged_source), filename=unchanged_source.name)

    await processor.process_item(
        UploadTask(task_id="task-unchanged", total_files=1),
        str(unchanged_source),
        unchanged_task,
    )

    assert unchanged_task.status == TaskStatus.COMPLETED
    assert not unchanged_source.exists()
    assert not list(get_indexed_documents_path().rglob("*"))


@pytest.mark.asyncio
async def test_traditional_processor_does_not_orphan_archive_when_hash_is_unchanged(
    archive_environment,
):
    """Roll back staging when duplicate content does not require indexing."""
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
    """Commit the original source after successful Langflow ingestion."""
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
