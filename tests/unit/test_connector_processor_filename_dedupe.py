"""Filename-based dedupe gate on connector ingest paths.

Covers the symmetric behavior introduced so that picking a file from the
SharePoint UI when a same-named document already exists triggers the
"Overwrite" dialog (frontend) or fails the file task (backend, when
``replace_duplicates`` is not set).
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.base import ConnectorDocument, DocumentACL
from models.processors import ConnectorFileProcessor, LangflowConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask


def _make_document(filename: str = "My Report.pdf") -> ConnectorDocument:
    return ConnectorDocument(
        id="doc-id-1",
        filename=filename,
        mimetype="application/pdf",
        content=b"%PDF-1.4 dummy",
        source_url="https://example.sharepoint.com/file.pdf",
        acl=DocumentACL(owner="user@example.com"),
        modified_time=datetime.now(),
        created_time=datetime.now(),
    )


def _make_search_response(has_hit: bool) -> dict:
    return {"hits": {"hits": [{"_id": "x"}] if has_hit else []}}


def _make_upload_task() -> UploadTask:
    return UploadTask(task_id="task-1", total_files=1)


def _make_file_task() -> FileTask:
    return FileTask(file_path="file-id-1")


def _build_connector_processor(replace_duplicates: bool) -> ConnectorFileProcessor:
    document_service = MagicMock()
    document_service.docling_service = MagicMock()
    document_service.session_manager = MagicMock()
    document_service.session_manager.get_user_opensearch_client = MagicMock()
    connector_service = MagicMock()
    return ConnectorFileProcessor(
        connector_service=connector_service,
        connection_id="conn-1",
        files_to_process=["file-id-1"],
        user_id="user-1",
        jwt_token="jwt",
        document_service=document_service,
        models_service=MagicMock(),
        replace_duplicates=replace_duplicates,
    )


def _wire_connector_processor(
    processor: ConnectorFileProcessor,
    document: ConnectorDocument,
    filename_exists: bool,
):
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(return_value=_make_search_response(filename_exists))
    opensearch_client.delete_by_query = AsyncMock(return_value={"deleted": 3})
    opensearch_client.exists = AsyncMock(return_value=False)
    processor.document_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )

    connector = MagicMock()
    connector.get_file_content = AsyncMock(return_value=document)
    processor.connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "sharepoint"
    processor.connector_service.connection_manager = MagicMock()
    processor.connector_service.connection_manager.get_connection = AsyncMock(
        return_value=connection
    )
    return opensearch_client


@pytest.mark.asyncio
async def test_connector_processor_fails_when_filename_exists_and_replace_false():
    processor = _build_connector_processor(replace_duplicates=False)
    document = _make_document()
    opensearch_client = _wire_connector_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(processor, "process_document_standard", new=AsyncMock()) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.FAILED
    assert "already exists" in (file_task.error or "")
    assert upload_task.failed_files == 1
    assert upload_task.successful_files == 0
    mock_process.assert_not_called()
    opensearch_client.delete_by_query.assert_not_called()


@pytest.mark.asyncio
async def test_connector_processor_deletes_then_ingests_when_replace_true():
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document()
    opensearch_client = _wire_connector_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-1"}),
    ) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    opensearch_client.delete_by_query.assert_awaited()
    mock_process.assert_awaited_once()
    # The processed filename must be the original (with space), not a
    # sanitized variant.
    assert mock_process.await_args.kwargs["original_filename"] == "My Report.pdf"


@pytest.mark.asyncio
async def test_connector_processor_deletes_chunks_when_source_returns_404():
    """When the source connector reports the file is gone (404), the processor
    must remove the already-indexed chunks for that document_id. Regression
    test for SharePoint sync leaving orphan chunks after a source-side delete.
    """
    processor = _build_connector_processor(replace_duplicates=False)

    opensearch_client = AsyncMock()
    # collect_visible_document_ids issues a scroll search; return one chunk _id
    opensearch_client.search = AsyncMock(
        return_value={"hits": {"hits": [{"_id": "chunk-1"}]}, "_scroll_id": None}
    )
    # delete_document_ids issues individual deletes per _id
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
    processor.document_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )

    connector = MagicMock()
    connector.get_file_content = AsyncMock(side_effect=FileNotFoundError("404 Not Found"))
    processor.connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "sharepoint"
    processor.connector_service.connection_manager = MagicMock()
    processor.connector_service.connection_manager.get_connection = AsyncMock(
        return_value=connection
    )

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert (file_task.result or {}).get("reason") == "deleted_at_source"
    assert (file_task.result or {}).get("deleted_chunks") == 1
    assert upload_task.successful_files == 1
    opensearch_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_connector_processor_proceeds_when_filename_absent():
    processor = _build_connector_processor(replace_duplicates=False)
    document = _make_document()
    opensearch_client = _wire_connector_processor(processor, document, filename_exists=False)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-1"}),
    ) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    opensearch_client.delete_by_query.assert_not_called()
    mock_process.assert_awaited_once()


def _build_langflow_processor(
    replace_duplicates: bool,
) -> LangflowConnectorFileProcessor:
    langflow_service = MagicMock()
    langflow_service.task_service = MagicMock()
    langflow_service.task_service.document_service = MagicMock()
    langflow_service.task_service.models_service = MagicMock()
    langflow_service.docling_service = MagicMock()
    langflow_service.session_manager = MagicMock()
    langflow_service.session_manager.get_user_opensearch_client = MagicMock()
    langflow_service.process_connector_document = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )
    return LangflowConnectorFileProcessor(
        langflow_connector_service=langflow_service,
        connection_id="conn-1",
        files_to_process=["file-id-1"],
        user_id="user-1",
        jwt_token="jwt",
        replace_duplicates=replace_duplicates,
    )


def _wire_langflow_processor(
    processor: LangflowConnectorFileProcessor,
    document: ConnectorDocument,
    filename_exists: bool,
    hash_exists: bool = False,
):
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(return_value=_make_search_response(filename_exists))
    opensearch_client.delete_by_query = AsyncMock(return_value={"deleted": 2})
    opensearch_client.exists = AsyncMock(return_value=hash_exists)
    processor.langflow_connector_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )

    connector = MagicMock()
    connector.get_file_content = AsyncMock(return_value=document)
    processor.langflow_connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "sharepoint"
    processor.langflow_connector_service.connection_manager = MagicMock()
    processor.langflow_connector_service.connection_manager.get_connection = AsyncMock(
        return_value=connection
    )
    return opensearch_client


@pytest.mark.asyncio
async def test_langflow_connector_processor_fails_on_filename_collision():
    processor = _build_langflow_processor(replace_duplicates=False)
    document = _make_document()
    opensearch_client = _wire_langflow_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.FAILED
    assert "already exists" in (file_task.error or "")
    assert upload_task.failed_files == 1
    processor.langflow_connector_service.process_connector_document.assert_not_called()
    opensearch_client.delete_by_query.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_connector_processor_overwrites_when_replace_true():
    processor = _build_langflow_processor(replace_duplicates=True)
    document = _make_document()
    opensearch_client = _wire_langflow_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    opensearch_client.delete_by_query.assert_awaited()
    processor.langflow_connector_service.process_connector_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_connector_processor_deletes_chunks_when_source_returns_404():
    """When the source connector reports the file is gone (404), the Langflow
    processor must remove the already-indexed chunks instead of surfacing
    'File not found: <id>' as a task error. Regression test for SharePoint
    webhook-triggered sync of a deleted source file.
    """
    processor = _build_langflow_processor(replace_duplicates=False)

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={"hits": {"hits": [{"_id": "chunk-1"}]}, "_scroll_id": None}
    )
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
    processor.langflow_connector_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )

    connector = MagicMock()
    connector.get_file_content = AsyncMock(
        side_effect=ValueError("File not found: 01BYMO7NCRKVAJFSPPABBKQXS4PPDHBVUY")
    )
    processor.langflow_connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "sharepoint"
    processor.langflow_connector_service.connection_manager = MagicMock()
    processor.langflow_connector_service.connection_manager.get_connection = AsyncMock(
        return_value=connection
    )

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert (file_task.result or {}).get("reason") == "deleted_at_source"
    assert (file_task.result or {}).get("deleted_chunks") == 1
    assert file_task.error is None
    assert upload_task.successful_files == 1
    assert upload_task.failed_files == 0
    processor.langflow_connector_service.process_connector_document.assert_not_called()
    opensearch_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_connector_processor_hash_unchanged_path_preserved():
    """When the filename is new but the byte hash already exists, the file
    is reported as 'unchanged' — same as before this change."""
    processor = _build_langflow_processor(replace_duplicates=False)
    document = _make_document()
    _wire_langflow_processor(processor, document, filename_exists=False, hash_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert (file_task.result or {}).get("status") == "unchanged"
    processor.langflow_connector_service.process_connector_document.assert_not_called()
