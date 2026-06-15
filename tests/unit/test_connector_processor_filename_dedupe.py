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
from models.processors import ConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from utils.file_utils import get_filename_aliases


@pytest.fixture(autouse=True)
def backend_write_client(monkeypatch):
    """Provide a backend OpenSearch write client (clients.opensearch).

    Chunk deletion (delete_document_by_filename, _delete_connector_chunks) writes
    through this singleton; it is None in unit tests, so patch it to a mock whose
    per-id delete reports success."""
    import config.settings as cfg

    client = AsyncMock()
    client.delete = AsyncMock(return_value={"result": "deleted"})
    monkeypatch.setattr(cfg.clients, "opensearch", client)
    return client


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
    connector_service._update_connector_metadata = AsyncMock()
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
    hash_exists: bool = False,
    rename_stale_exists: bool = False,
):
    opensearch_client = AsyncMock()

    async def mock_search(index, body, **kwargs):
        query_str = str(body)
        # Rename-cleanup query is the only one referencing connector_file_id
        # (dual-id should clause); check it first since it also mentions
        # document_id.
        if "connector_file_id" in query_str:
            return _make_search_response(rename_stale_exists)
        if "document_id" in query_str:
            return _make_search_response(hash_exists)
        return _make_search_response(filename_exists)

    opensearch_client.search = mock_search
    opensearch_client.delete_by_query = AsyncMock(return_value={"deleted": 3})
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
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
async def test_connector_processor_skips_when_filename_exists_and_replace_false(monkeypatch):
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=False)
    document = _make_document()
    opensearch_client = _wire_connector_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(processor, "process_document_standard", new=AsyncMock()) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.error is None
    assert file_task.result == {
        "status": "skipped",
        "reason": "duplicate_filename",
        "warning": "A file with this name already exists.",
    }
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 1
    mock_process.assert_not_called()
    opensearch_client.delete_by_query.assert_not_called()


@pytest.mark.asyncio
async def test_connector_processor_deletes_then_ingests_when_replace_true(
    monkeypatch, backend_write_client
):
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document()
    _wire_connector_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-1"}),
    ) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    # The existing same-name chunks are removed via the backend write client's
    # per-id delete before re-ingest.
    backend_write_client.delete.assert_awaited()
    mock_process.assert_awaited_once()
    # The processed filename must be the original (with space), not a
    # sanitized variant.
    assert mock_process.await_args.kwargs["original_filename"] == "My Report.pdf"


@pytest.mark.asyncio
async def test_connector_processor_deletes_chunks_when_source_returns_404(
    monkeypatch, backend_write_client
):
    """When the source connector reports the file is gone (404), the processor
    must remove the already-indexed chunks by the stable connector id, matching
    BOTH connector_file_id (standard path; document_id holds the content hash)
    and document_id (Langflow path). Querying document_id alone would miss
    standard-path chunks.
    """
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=False)

    opensearch_client = AsyncMock()
    # collect_visible_document_ids issues a scroll search; return one chunk _id
    opensearch_client.search = AsyncMock(
        return_value={"hits": {"hits": [{"_id": "chunk-1"}]}, "_scroll_id": None}
    )
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
    # Concrete chunk deletes go through the backend write client.
    backend_write_client.delete.assert_awaited_once()

    # The cleanup must match BOTH id fields (a single document_id terms query
    # would miss standard-path chunks whose document_id is the content hash).
    search_call = opensearch_client.search.await_args
    query = search_call.kwargs["body"]["query"]
    shoulds = query["bool"]["filter"][0]["bool"]["should"]
    fields = {next(iter(c["term"])): next(iter(c["term"].values())) for c in shoulds}
    assert fields["connector_file_id"] == "file-id-1"
    assert fields["document_id"] == "file-id-1"


@pytest.mark.asyncio
async def test_connector_processor_proceeds_when_filename_absent(monkeypatch):
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
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
) -> ConnectorFileProcessor:
    processor = _build_connector_processor(replace_duplicates)

    langflow_service = MagicMock()
    langflow_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )
    langflow_service.merge_ui_ingest_settings_into_tweaks = MagicMock(return_value={})

    processor.connector_service.langflow_service = langflow_service
    processor.connector_service.task_service = MagicMock()
    processor.connector_service.task_service.docling_polling_service = MagicMock()

    return processor


def _wire_langflow_processor(
    processor: ConnectorFileProcessor,
    document: ConnectorDocument,
    filename_exists: bool,
    hash_exists: bool = False,
    rename_stale_exists: bool = False,
):
    opensearch_client = AsyncMock()

    async def mock_search(index, body, **kwargs):
        query_str = str(body)
        if "connector_file_id" in query_str:
            return _make_search_response(rename_stale_exists)
        if "document_id" in query_str:
            return _make_search_response(hash_exists)
        return _make_search_response(filename_exists)

    opensearch_client.search = mock_search
    opensearch_client.delete_by_query = AsyncMock(return_value={"deleted": 2})
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
    opensearch_client.exists = AsyncMock(return_value=hash_exists)

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
async def test_langflow_connector_processor_skips_on_filename_collision(monkeypatch):
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", False)
    processor = _build_langflow_processor(replace_duplicates=False)
    document = _make_document()
    opensearch_client = _wire_langflow_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.error is None
    assert file_task.result == {
        "status": "skipped",
        "reason": "duplicate_filename",
        "warning": "A file with this name already exists.",
    }
    assert upload_task.failed_files == 0
    assert upload_task.successful_files == 1
    processor.connector_service.langflow_service.upload_and_ingest_file.assert_not_called()
    opensearch_client.delete_by_query.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_connector_processor_overwrites_when_replace_true(
    monkeypatch, backend_write_client
):
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", False)
    processor = _build_langflow_processor(replace_duplicates=True)
    document = _make_document()
    _wire_langflow_processor(processor, document, filename_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    # The existing same-name chunks are removed (per-id delete via the backend
    # write client) before re-uploading to Langflow.
    backend_write_client.delete.assert_awaited()
    processor.connector_service.langflow_service.upload_and_ingest_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_connector_processor_deletes_chunks_when_source_returns_404(
    monkeypatch, backend_write_client
):
    """When the source connector reports the file is gone (404), the Langflow
    processor must remove the already-indexed chunks instead of surfacing
    'File not found: <id>' as a task error. Regression test for SharePoint
    webhook-triggered sync of a deleted source file.
    """
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", False)
    processor = _build_langflow_processor(replace_duplicates=False)

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={"hits": {"hits": [{"_id": "chunk-1"}]}, "_scroll_id": None}
    )
    processor.document_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )

    connector = MagicMock()
    connector.get_file_content = MagicMock()
    connector.get_file_content.side_effect = ValueError(
        "File not found: 01BYMO7NCRKVAJFSPPABBKQXS4PPDHBVUY"
    )
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
    assert file_task.error is None
    assert upload_task.successful_files == 1
    assert upload_task.failed_files == 0
    processor.connector_service.langflow_service.upload_and_ingest_file.assert_not_called()
    backend_write_client.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_connector_processor_hash_unchanged_path_preserved(monkeypatch):
    """When the filename is new but the byte hash already exists, the file
    is reported as 'unchanged' — same as before this change."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", False)
    processor = _build_langflow_processor(replace_duplicates=False)
    document = _make_document()
    _wire_langflow_processor(processor, document, filename_exists=False, hash_exists=True)

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    await processor.process_item(upload_task, "file-id-1", file_task)

    assert file_task.status == TaskStatus.COMPLETED
    assert (file_task.result or {}).get("status") == "unchanged"
    processor.connector_service.langflow_service.upload_and_ingest_file.assert_not_called()


# ---------------------------------------------------------------------------
# Rename cleanup: a connector file keeps a stable id across renames, so the
# OLD-name chunks must be removed when it is re-ingested under a new name.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pure_rename_deletes_old_chunks_and_reingests(monkeypatch, backend_write_client):
    """Unchanged content + new name (standard path): the stale old-name chunks
    are deleted and the file is re-ingested under the new name, instead of
    short-circuiting as 'unchanged' and leaving the old name behind."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document(filename="Renamed.pdf")
    # hash_exists=True (content unchanged) but a stale-name chunk exists.
    _wire_connector_processor(
        processor, document, filename_exists=False, hash_exists=True, rename_stale_exists=True
    )

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-1"}),
    ) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    # Old-name chunks removed, and the unchanged short-circuit was bypassed.
    backend_write_client.delete.assert_awaited()
    mock_process.assert_awaited_once()
    assert file_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_no_rename_unchanged_still_short_circuits(monkeypatch, backend_write_client):
    """No rename + unchanged content: nothing is deleted and the file is
    reported 'unchanged' (no needless re-ingest)."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document()
    _wire_connector_processor(
        processor, document, filename_exists=False, hash_exists=True, rename_stale_exists=False
    )

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(processor, "process_document_standard", new=AsyncMock()) as mock_process:
        await processor.process_item(upload_task, "file-id-1", file_task)

    assert (file_task.result or {}).get("status") == "unchanged"
    mock_process.assert_not_called()
    backend_write_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_rename_cleanup_matches_both_id_fields(monkeypatch, backend_write_client):
    """The rename-cleanup query must match BOTH document_id and
    connector_file_id, and exclude the current filename (and its aliases)."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document(filename="Renamed.pdf")

    captured = {}
    opensearch_client = AsyncMock()

    async def mock_search(index, body, **kwargs):
        query_str = str(body)
        if "connector_file_id" in query_str:
            captured["query"] = body["query"]
            return {"hits": {"hits": []}}
        return {"hits": {"hits": []}}

    opensearch_client.search = mock_search
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

    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-1"}),
    ):
        await processor.process_item(
            upload_task=_make_upload_task(), item="file-id-1", file_task=_make_file_task()
        )

    shoulds = captured["query"]["bool"]["filter"][0]["bool"]["should"]
    fields = {next(iter(c["term"])) for c in shoulds}
    assert fields == {"document_id", "connector_file_id"}
    excluded = captured["query"]["bool"]["must_not"][0]["terms"]["filename"]
    assert set(get_filename_aliases("Renamed.pdf")).issubset(set(excluded))


@pytest.mark.asyncio
async def test_rename_cleanup_is_best_effort(monkeypatch, backend_write_client):
    """A failure during rename cleanup must not fail the task."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_connector_processor(replace_duplicates=True)
    document = _make_document()
    _wire_connector_processor(processor, document, filename_exists=False, hash_exists=True)
    # Make the chunk delete blow up; cleanup swallows it and returns 0.
    backend_write_client.delete = AsyncMock(side_effect=RuntimeError("opensearch down"))

    file_task = _make_file_task()
    upload_task = _make_upload_task()

    with patch.object(processor, "process_document_standard", new=AsyncMock()):
        await processor.process_item(upload_task, "file-id-1", file_task)

    # Task still finishes (unchanged short-circuit, since cleanup found/deleted nothing).
    assert file_task.status == TaskStatus.COMPLETED
