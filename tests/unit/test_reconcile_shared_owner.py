"""Unit tests for ConnectorFileProcessor._reconcile_shared_owner.

Covers the bug where re-syncing a COS bucket with "Make documents available
to all users" newly toggled left already-indexed (unchanged content /
duplicate filename) chunks with stale, non-shared ownership, since the
resolve_shared_owner_fields() recompute is normally only reached on a fresh
index write.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import config.settings as settings_module
from models.processors import ConnectorFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from utils.filename_claims import filename_claims


def _make_processor(*, shared: bool, user_id: str = "user-1"):
    return ConnectorFileProcessor(
        connector_service=None,
        connection_id="conn-1",
        files_to_process=[],
        user_id=user_id,
        owner_name="Alice",
        owner_email="alice@example.com",
        shared=shared,
        allow_anonymous_delete=True,
    )


async def _reconcile(processor, shared: bool, *, file_is_shared: bool | None = None):
    """Run the reconcile for report.pdf, with the index answering
    ``file_is_shared`` to "is this file itself indexed as shared?"."""
    processor._indexed_shared_state = AsyncMock(return_value=file_is_shared)
    await processor._reconcile_shared_owner(
        "report.pdf",
        shared,
        file_id="file-abc",
        opensearch_client=AsyncMock(),
        connector_type="ibm_cos",
    )


@pytest.fixture(autouse=True)
def _restore_write_client():
    original = settings_module.clients.opensearch
    yield
    settings_module.clients.opensearch = original


@pytest.mark.asyncio
async def test_reconcile_shared_true_omits_owner_via_script():
    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client
    processor = _make_processor(shared=True)

    await _reconcile(processor, True)

    assert write_client.update_by_query.await_count >= 1
    call = write_client.update_by_query.await_args_list[0]
    body = call.kwargs["body"]
    assert body["query"]["bool"]["filter"][0] == {"term": {"filename": "report.pdf"}}
    params = body["script"]["params"]
    assert params["shared"] is True
    assert params["owner"] is None
    assert params["owner_name"] == "Anonymous User"
    assert params["owner_email"] == "anonymous@localhost"
    assert "ctx._source.remove('owner')" in body["script"]["source"]


@pytest.mark.asyncio
async def test_reconcile_shared_false_sets_owner_via_script():
    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client
    processor = _make_processor(shared=False)

    await _reconcile(processor, False)

    call = write_client.update_by_query.await_args_list[0]
    params = call.kwargs["body"]["script"]["params"]
    assert params["shared"] is False
    assert params["owner"] == "user-1"
    assert params["owner_name"] == "Alice"
    assert params["owner_email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_reconcile_shared_owner_noop_without_write_client():
    settings_module.clients.opensearch = None
    processor = _make_processor(shared=True)

    # Must not raise even though there's nothing to write to.
    await _reconcile(processor, True)


@pytest.mark.asyncio
async def test_reconcile_shared_owner_swallows_update_errors():
    write_client = AsyncMock()
    write_client.update_by_query.side_effect = RuntimeError("boom")
    settings_module.clients.opensearch = write_client
    processor = _make_processor(shared=True)

    # A failed reconciliation must not fail the (already-skipped) sync item.
    await _reconcile(processor, True)


@pytest.mark.asyncio
async def test_reconcile_without_permission_leaves_a_shared_namesake_alone():
    """A private sync whose filename collides with someone else's SHARED
    document must not claim it.

    The script writes an owner onto whatever it matches, so the wider
    "mine OR ownerless" scope would hand a document visible to the whole
    instance to the syncing user — silently, and without the
    knowledge:delete:anonymous check that deliberate shared deletion goes
    through. Without the permission the scope is the caller's own chunks,
    whatever the index says about the file.
    """
    from utils.opensearch_queries import build_owned_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=False)
    processor.allow_anonymous_delete = False

    await _reconcile(processor, False, file_is_shared=True)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_owned_filename_query("report.pdf", "user-1")
    # Not even asked: nothing it could answer would widen the scope.
    processor._indexed_shared_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_of_the_files_own_shared_copy_keeps_the_wider_scope():
    """Granted (and with RBAC unenforced, which resolves to granted), and with
    this file itself indexed as shared, the reconcile reaches the ownerless
    chunks. That is the share-all toggle being switched off for a file whose
    content has not changed: the ownerless chunks are this file's own."""
    from utils.opensearch_queries import build_replace_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=False)
    processor.allow_anonymous_delete = True

    await _reconcile(processor, False, file_is_shared=True)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_replace_filename_query("report.pdf", "user-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("file_is_shared", [False, None], ids=["indexed-private", "not-indexed"])
async def test_a_private_sync_cannot_claim_a_shared_namesake(file_is_shared):
    """The permission alone used to be enough, and the script matches by
    filename. So a private sync by someone holding it — an admin, or anyone at
    all where RBAC is not enforced — wrote itself as owner onto a shared
    document from another source that merely had the same name: no delete, no
    prompt, and gone from everyone else's view.

    What tells the two apart is the file id. A namesake is a document this
    connector never ingested, so the index does not say this file is shared.
    """
    from utils.opensearch_queries import build_owned_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=False)
    processor.allow_anonymous_delete = True

    await _reconcile(processor, False, file_is_shared=file_is_shared)

    body = write_client.update_by_query.await_args.kwargs["body"]
    assert body["query"] == build_owned_filename_query("report.pdf", "user-1")
    assert body["script"]["params"]["owner"] == "user-1"


@pytest.mark.asyncio
async def test_resolving_to_shared_does_not_stand_in_for_the_permission():
    """``shared`` used to widen the scope on its own, on the reasoning that a
    shared write had cleared the permission upstream. On the re-sync paths it
    is inherited from the index, which nobody was authorized to decide."""
    from utils.opensearch_queries import build_owned_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=True)
    processor.allow_anonymous_delete = False

    await _reconcile(processor, True, file_is_shared=True)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_owned_filename_query("report.pdf", "user-1")


def _connector_processor_for(filename: str, *, indexed: bool):
    """A ConnectorFileProcessor wired far enough to reach the duplicate gate."""
    from types import SimpleNamespace

    processor = _make_processor(shared=False)
    document = SimpleNamespace(
        id="file-abc",
        filename=filename,
        mimetype="application/pdf",
        content=b"%PDF-",
        acl=None,
    )
    connector = AsyncMock()
    connector.get_file_content = AsyncMock(return_value=document)
    connector.CONNECTOR_TYPE = "ibm_cos"
    connector_service = AsyncMock()
    connector_service.get_connector = AsyncMock(return_value=connector)
    connector_service.connection_manager.get_connection = AsyncMock(
        return_value=SimpleNamespace(connector_type="ibm_cos")
    )
    processor.connector_service = connector_service
    processor.document_service = MagicMock()
    processor.session_manager = MagicMock()
    processor.check_filename_exists = AsyncMock(return_value=indexed)
    processor._reconcile_shared_owner = AsyncMock()
    return processor


@pytest.mark.asyncio
async def test_losing_an_in_flight_claim_does_not_reconcile():
    """The reconcile matches by filename, so running it for a claim loser would
    rewrite owner fields on the chunks the WINNER is writing — a different
    document, whose sharing state was resolved from its own file id and can
    differ from this one's. Nothing is indexed under the name by this file, so
    there is nothing of its own to reconcile.
    """
    processor = _connector_processor_for("report.pdf", indexed=False)
    upload_task = UploadTask(task_id="task-1", total_files=2)
    file_task = FileTask(file_path="cos::b/report.pdf", filename="report.pdf")

    # Another file in this batch already holds the name.
    filename_claims.claim("task-1:winner", "report.pdf", owner_user_id="user-1", shared=False)

    await processor.process_item(upload_task, "cos::b/report.pdf", file_task)

    assert file_task.status is TaskStatus.SKIPPED
    assert file_task.result["reason"] == "duplicate_filename"
    processor._reconcile_shared_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refused_replacement_does_not_reconcile():
    """A replace that deleted nothing means the document under this name is not
    this caller's to replace. It is not this file's own either, so there is
    nothing to bring in line — and reconciling would write owner fields onto a
    document the caller was just told they may not touch."""
    processor = _connector_processor_for("report.pdf", indexed=True)
    processor.replace_duplicates = True
    processor.delete_document_by_filename = AsyncMock(return_value=0)
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path="cos::b/report.pdf", filename="report.pdf")

    await processor.process_item(upload_task, "cos::b/report.pdf", file_task)

    assert file_task.status is TaskStatus.SKIPPED
    assert "permission to replace" in file_task.result["warning"]
    processor._reconcile_shared_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_real_duplicate_still_reconciles():
    """The document indexed under this name IS this file's own, so the owner
    fields still get brought in line with the connector's current setting."""
    processor = _connector_processor_for("report.pdf", indexed=True)
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path="cos::b/report.pdf", filename="report.pdf")

    await processor.process_item(upload_task, "cos::b/report.pdf", file_task)

    assert file_task.status is TaskStatus.SKIPPED
    processor._reconcile_shared_owner.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_gate_reports_the_two_skips_apart():
    """The indexed document under this name IS this file's own, so the caller
    reconciles as before."""
    processor = _make_processor(shared=False)
    processor.check_filename_exists = AsyncMock(return_value=True)

    action = await processor.resolve_duplicate_filename(
        "report.pdf",
        AsyncMock(),
        replace=False,
        owner_user_id="user-1",
        claim_holder="task-1:only",
        allow_anonymous_delete=True,
    )

    assert action == "skip"
