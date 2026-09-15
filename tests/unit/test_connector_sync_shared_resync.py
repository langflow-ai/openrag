"""Re-syncing a COS file that was ingested as shared must update it in place.

Regression test for "overwrite a file in COS is not reflected after syncing
connectors". The share-all toggle indexes chunks with no ``owner`` field, and
nothing persists that choice, so the re-sync paths (Sync all connectors, and
``/connectors/{type}/sync`` with an empty body) used to run with shared=False.
Every owner-scoped step downstream then missed the ownerless chunks: the
replace-delete matched nothing, ``resolve_duplicate_filename`` reported the file
as an unreplaceable duplicate and skipped it, and ``_reconcile_shared_owner``
stamped the current user onto the chunks on the way out — so the modified object
never reached the index and the document silently lost its shared status.

Those paths now pass shared=None ("no explicit intent") and each file inherits
the sharing state it already has in the index. An explicit toggle value still
wins, so a user can still flip a document between shared and private.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.base import ConnectorDocument, DocumentACL
from models.processors import ConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

COS_FILE_ID = "my-bucket::reports/q3.pdf"
COS_FILENAME = "q3.pdf"


@pytest.fixture(autouse=True)
def backend_write_client(monkeypatch):
    """Backend OpenSearch write client (clients.opensearch) used for deletes."""
    import config.settings as cfg

    client = AsyncMock()
    client.delete = AsyncMock(return_value={"result": "deleted"})
    monkeypatch.setattr(cfg.clients, "opensearch", client)
    return client


def _make_document() -> ConnectorDocument:
    return ConnectorDocument(
        id=COS_FILE_ID,
        filename=COS_FILENAME,
        mimetype="application/pdf",
        content=b"%PDF-1.4 updated bytes",
        source_url=f"cos://{COS_FILE_ID}",
        acl=DocumentACL(owner="service-instance-1"),
        modified_time=datetime.now(),
        created_time=datetime.now(),
    )


def _build_processor(*, shared: bool | None) -> ConnectorFileProcessor:
    document_service = MagicMock()
    document_service.docling_service = MagicMock()
    document_service.session_manager = MagicMock()
    document_service.session_manager.get_user_opensearch_client = MagicMock()
    connector_service = MagicMock()
    connector_service._update_connector_metadata = AsyncMock()
    return ConnectorFileProcessor(
        connector_service=connector_service,
        connection_id="conn-1",
        files_to_process=[COS_FILE_ID],
        user_id="user-1",
        jwt_token="jwt",
        owner_name="Alice",
        owner_email="alice@example.com",
        document_service=document_service,
        models_service=MagicMock(),
        # Timestamp change detection re-ingests changed blobs with replace on.
        replace_duplicates=True,
        connector_type="ibm_cos",
        shared=shared,
    )


def _owner_clause_matches(query: dict, indexed_owner) -> bool:
    """Apply a query's owner scoping to the indexed chunks, the way OpenSearch would.

    The whole defect lives in this filter, so the fake has to honor it rather
    than returning hits unconditionally: an owner-only term does not match
    ownerless (shared) chunks, which is what made the replace-delete remove
    nothing and the file get skipped as an unreplaceable duplicate.
    """
    for clause in query.get("bool", {}).get("filter", []):
        term_owner = clause.get("term", {}).get("owner")
        if term_owner is not None:
            return indexed_owner == term_owner
        inner = clause.get("bool", {})
        if inner.get("must_not") == {"exists": {"field": "owner"}}:
            return indexed_owner is None
        shoulds = inner.get("should")
        if shoulds and any("owner" in str(s) for s in shoulds):
            # owner == me OR owner absent
            owners = [s.get("term", {}).get("owner") for s in shoulds]
            return indexed_owner is None or indexed_owner in owners
    return True  # unscoped query


def _wire(processor: ConnectorFileProcessor, document: ConnectorDocument, *, indexed_owner):
    """Wire an OpenSearch client for a file already indexed under ``indexed_owner``.

    ``indexed_owner`` is the ``owner`` value on the existing chunks: None models
    a share-all ingest (field absent), a string models a private one, and
    ``"absent"`` models a file that is not indexed at all.
    """
    opensearch_client = AsyncMock()

    async def mock_search(index, body, **kwargs):
        # 1. Indexed-sharing-state probe: the only search asking for _source owner.
        if body.get("_source") == ["owner"]:
            if indexed_owner == "absent":
                return {"hits": {"hits": []}}
            source = {} if indexed_owner is None else {"owner": indexed_owner}
            return {"hits": {"hits": [{"_id": "chunk-1", "_source": source}]}}
        # 2. Bulk filename duplicate check (terms aggregation).
        if "aggs" in body:
            buckets = [] if indexed_owner == "absent" else [{"key": COS_FILENAME, "doc_count": 1}]
            return {"aggregations": {"filenames": {"buckets": buckets}}}
        query = body.get("query", {})
        query_str = str(query)
        # 3. Rename cleanup by connector file id — nothing stale under an old name.
        if "connector_file_id" in query_str:
            return {"hits": {"hits": []}}
        # 4. Replace-delete id collection for the filename, owner scoping applied.
        if "filename" in query_str:
            if indexed_owner == "absent" or not _owner_clause_matches(query, indexed_owner):
                return {"hits": {"hits": []}}
            return {"hits": {"hits": [{"_id": "chunk-1"}, {"_id": "chunk-2"}]}}
        # 5. Content-hash check: the overwritten bytes hash to something new.
        return {"hits": {"hits": []}}

    opensearch_client.search = mock_search
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})

    connector = MagicMock()
    connector.get_file_content = AsyncMock(return_value=document)
    processor.connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "ibm_cos"
    processor.connector_service.connection_manager = MagicMock()
    processor.connector_service.connection_manager.get_connection = AsyncMock(
        return_value=connection
    )
    processor.document_service.session_manager.get_user_opensearch_client.return_value = (
        opensearch_client
    )
    return opensearch_client


async def _run(processor) -> tuple[FileTask, UploadTask, AsyncMock]:
    file_task = FileTask(file_path=COS_FILE_ID)
    upload_task = UploadTask(task_id="task-1", total_files=1)
    with patch.object(
        processor,
        "process_document_standard",
        new=AsyncMock(return_value={"status": "indexed", "id": "hash-new"}),
    ) as mock_process:
        await processor.process_item(upload_task, COS_FILE_ID, file_task)
    return file_task, upload_task, mock_process


@pytest.mark.asyncio
async def test_resync_replaces_shared_cos_file_and_keeps_it_shared(
    monkeypatch, backend_write_client
):
    """The defect: an overwritten COS object indexed as shared must be re-ingested."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=None)
    _wire(processor, _make_document(), indexed_owner=None)

    file_task, upload_task, mock_process = await _run(processor)

    # Not skipped as a duplicate — the stale chunks were deleted and the new
    # bytes went through ingestion.
    assert file_task.status == TaskStatus.COMPLETED
    assert file_task.result["status"] == "indexed"
    assert upload_task.successful_files == 1
    backend_write_client.delete.assert_awaited()
    mock_process.assert_awaited_once()
    # ...and it stays shared, rather than being quietly reassigned to the
    # user who happened to run the sync.
    assert mock_process.await_args.kwargs["shared"] is True


@pytest.mark.asyncio
async def test_resync_keeps_private_cos_file_private(monkeypatch):
    """A file indexed with an owner is re-ingested private, not shared."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=None)
    _wire(processor, _make_document(), indexed_owner="user-1")

    file_task, _, mock_process = await _run(processor)

    assert file_task.status == TaskStatus.COMPLETED
    mock_process.assert_awaited_once()
    assert mock_process.await_args.kwargs["shared"] is False


@pytest.mark.asyncio
async def test_explicit_shared_false_overrides_indexed_state(monkeypatch):
    """The UI toggle still wins: an explicit False makes a shared file private."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=False)
    _wire(processor, _make_document(), indexed_owner=None)

    file_task, _, mock_process = await _run(processor)

    assert file_task.status == TaskStatus.COMPLETED
    mock_process.assert_awaited_once()
    assert mock_process.await_args.kwargs["shared"] is False


@pytest.mark.asyncio
async def test_new_file_with_no_intent_falls_back_to_private(monkeypatch):
    """A file that isn't indexed yet has no state to inherit → private."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=None)
    _wire(processor, _make_document(), indexed_owner="absent")

    file_task, _, mock_process = await _run(processor)

    assert file_task.status == TaskStatus.COMPLETED
    mock_process.assert_awaited_once()
    assert mock_process.await_args.kwargs["shared"] is False
