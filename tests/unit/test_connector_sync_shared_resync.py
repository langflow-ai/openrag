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
from models.processors import DUPLICATE_NOT_REPLACEABLE_WARNING, ConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from utils.opensearch_queries import build_owned_filename_query, build_replace_filename_query

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


def _build_processor(
    *, shared: bool | None, allow_anonymous_delete: bool = True
) -> ConnectorFileProcessor:
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
        allow_anonymous_delete=allow_anonymous_delete,
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
async def test_resync_without_the_permission_leaves_a_shared_file_alone(
    monkeypatch, backend_write_client
):
    """Inheriting a file's sharing state is not being allowed to replace it.

    The files a sync walks come from a query scoped by connector type and read
    through DLS, so they include shared files that another user's connection
    ingested. A caller without knowledge:delete:anonymous must not be able to
    delete and rewrite one of those by running an ordinary sync.
    """
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=None, allow_anonymous_delete=False)
    _wire(processor, _make_document(), indexed_owner=None)

    file_task, _, mock_process = await _run(processor)

    backend_write_client.delete.assert_not_awaited()
    mock_process.assert_not_awaited()
    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.result["reason"] == "duplicate_filename"
    # ...and it is still shared afterwards, because nothing touched it: a
    # refusal issues no update to the document it refused either.
    backend_write_client.update_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refused_overwrite_says_it_was_refused(monkeypatch, backend_write_client):
    """Share-all off, Overwrite confirmed, by someone who may not replace the
    shared document the name belongs to.

    The file is skipped either way; what matters here is the warning. It used
    to be the ordinary duplicate's "A file with this name already exists",
    which reads as a failure to someone who was just asked whether to overwrite
    and said yes.
    """
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=False, allow_anonymous_delete=False)
    _wire(processor, _make_document(), indexed_owner=None)

    file_task, upload_task, mock_process = await _run(processor)

    backend_write_client.delete.assert_not_awaited()
    mock_process.assert_not_awaited()
    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.result == {
        "status": "skipped",
        "reason": "duplicate_filename",
        "warning": DUPLICATE_NOT_REPLACEABLE_WARNING,
    }
    # Still a skip, not a failure: the task reports a warning, as before.
    assert upload_task.successful_files == 1
    assert upload_task.failed_files == 0
    # "You don't have permission to replace it" has to mean nothing was written.
    backend_write_client.update_by_query.assert_not_awaited()


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


# ---------------------------------------------------------------------------
# An inherited sharing state authorizes nothing
# ---------------------------------------------------------------------------


def _index_of_one_file(*, mine: bool, shared: bool) -> AsyncMock:
    """A user-scoped client over an index holding this file under either
    layout, or both: user-1's own copy, and a shared one another connection
    ingested from the same object.

    It honours the owner scope of the query the way OpenSearch would. Asked
    without one, it answers with the shared chunk first, which is the order
    that used to decide the matter.
    """
    own = {"_id": "mine", "_source": {"owner": "user-1"}}
    ownerless = {"_id": "shared", "_source": {}}

    async def search(index, body, **kwargs):
        filters = body["query"]["bool"]["filter"]
        if {"term": {"owner": "user-1"}} in filters:
            hits = [own] if mine else []
        elif {"bool": {"must_not": {"exists": {"field": "owner"}}}} in filters:
            hits = [ownerless] if shared else []
        else:
            hits = ([ownerless] if shared else []) + ([own] if mine else [])
        return {"hits": {"hits": hits[:1]}}

    client = AsyncMock()
    client.search = search
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mine, shared, expected",
    [
        pytest.param(True, True, False, id="both-layouts-mine-wins"),
        pytest.param(True, False, False, id="only-mine"),
        pytest.param(False, True, True, id="only-shared"),
        pytest.param(False, False, None, id="not-indexed"),
    ],
)
async def test_a_users_own_copy_decides_what_a_resync_inherits(mine, shared, expected):
    """One object can be indexed twice: privately by one user, and shared by
    another connection. A re-sync of the first user's is about their own copy.
    Taking whichever chunk the index returned first made it arbitrary, and when
    the shared one came back their private file was synced as the shared
    document."""
    processor = _build_processor(shared=None)

    state = await processor._indexed_shared_state(
        COS_FILE_ID, _index_of_one_file(mine=mine, shared=shared), "ibm_cos"
    )

    assert state is expected


@pytest.mark.asyncio
async def test_a_failed_sharing_lookup_inherits_nothing():
    client = AsyncMock()
    client.search = AsyncMock(side_effect=RuntimeError("opensearch is down"))
    processor = _build_processor(shared=None)

    assert await processor._indexed_shared_state(COS_FILE_ID, client, "ibm_cos") is None


@pytest.mark.asyncio
async def test_a_shared_file_is_refused_before_the_callers_namesake_is_touched(
    monkeypatch, backend_write_client
):
    """Sharing inherited, no permission, and the caller owns a private document
    with the same name from somewhere else.

    The duplicate gate only refuses a replace that deleted nothing. Here it
    deleted the caller's own namesake, so it was not refused, and the file went
    on to be indexed as shared: a shared write by someone not allowed to make
    one, added to the document everyone reads. The refusal has to come first.
    """
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=None, allow_anonymous_delete=False)
    client = _wire(processor, _make_document(), indexed_owner=None)
    search_shared_file = client.search

    async def search(index, body, **kwargs):
        query = body.get("query", {})
        if query == build_owned_filename_query(COS_FILENAME, "user-1"):
            return {"hits": {"hits": [{"_id": "mine-1"}, {"_id": "mine-2"}]}}
        return await search_shared_file(index, body, **kwargs)

    client.search = search

    file_task, _, mock_process = await _run(processor)

    backend_write_client.delete.assert_not_awaited()
    backend_write_client.update_by_query.assert_not_awaited()
    mock_process.assert_not_awaited()
    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.result["warning"] == DUPLICATE_NOT_REPLACEABLE_WARNING


def _decline_the_duplicate(processor, client, *, this_file_is_indexed: bool):
    """A sync that finds its filename taken and was not asked to replace it,
    which is where the owner reconcile runs. ``this_file_is_indexed`` False
    makes the name belong to a document from another source."""
    processor.replace_duplicates = False
    if this_file_is_indexed:
        return
    search_shared_file = client.search

    async def search(index, body, **kwargs):
        if body.get("_source") == ["owner"]:
            return {"hits": {"hits": []}}
        return await search_shared_file(index, body, **kwargs)

    client.search = search


@pytest.mark.asyncio
async def test_a_private_sync_does_not_claim_a_shared_document_with_the_same_name(
    monkeypatch, backend_write_client
):
    """The permission is held, the toggle is off, and the name belongs to a
    shared document this connector never ingested. The reconcile writes the
    caller in as owner of whatever it matches, and it matches by filename, so
    with the permission alone it took the shared document out of everyone
    else's view without a delete or a prompt."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=False, allow_anonymous_delete=True)
    client = _wire(processor, _make_document(), indexed_owner=None)
    _decline_the_duplicate(processor, client, this_file_is_indexed=False)

    file_task, _, _ = await _run(processor)

    assert file_task.status == TaskStatus.SKIPPED
    body = backend_write_client.update_by_query.await_args.kwargs["body"]
    assert body["query"] == build_owned_filename_query(COS_FILENAME, "user-1")


@pytest.mark.asyncio
async def test_switching_share_all_off_still_makes_the_files_own_copy_private(
    monkeypatch, backend_write_client
):
    """The other side of the same rule: when the shared document under the name
    IS this file's own, an explicit private sync by someone holding the
    permission still reaches it and writes the owner in."""
    monkeypatch.setattr("config.settings.DISABLE_INGEST_WITH_LANGFLOW", True)
    processor = _build_processor(shared=False, allow_anonymous_delete=True)
    client = _wire(processor, _make_document(), indexed_owner=None)
    _decline_the_duplicate(processor, client, this_file_is_indexed=True)

    file_task, _, _ = await _run(processor)

    assert file_task.status == TaskStatus.SKIPPED
    body = backend_write_client.update_by_query.await_args.kwargs["body"]
    assert body["query"] == build_replace_filename_query(COS_FILENAME, "user-1")
    assert body["script"]["params"]["shared"] is False
    assert body["script"]["params"]["owner"] == "user-1"
