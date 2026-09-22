"""Unit tests for ConnectorFileProcessor._reconcile_shared_owner.

Covers the bug where re-syncing a COS bucket with "Make documents available
to all users" newly toggled left already-indexed (unchanged content /
duplicate filename) chunks with stale, non-shared ownership, since the
resolve_shared_owner_fields() recompute is normally only reached on a fresh
index write.
"""

from unittest.mock import AsyncMock

import pytest

import config.settings as settings_module
from models.processors import ConnectorFileProcessor


def _make_processor(*, shared: bool, user_id: str = "user-1"):
    return ConnectorFileProcessor(
        connector_service=None,
        connection_id="conn-1",
        files_to_process=[],
        user_id=user_id,
        owner_name="Alice",
        owner_email="alice@example.com",
        shared=shared,
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

    await processor._reconcile_shared_owner("report.pdf", True)

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

    await processor._reconcile_shared_owner("report.pdf", False)

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
    await processor._reconcile_shared_owner("report.pdf", True)


@pytest.mark.asyncio
async def test_reconcile_shared_owner_swallows_update_errors():
    write_client = AsyncMock()
    write_client.update_by_query.side_effect = RuntimeError("boom")
    settings_module.clients.opensearch = write_client
    processor = _make_processor(shared=True)

    # A failed reconciliation must not fail the (already-skipped) sync item.
    await processor._reconcile_shared_owner("report.pdf", True)


@pytest.mark.asyncio
async def test_reconcile_without_permission_leaves_a_shared_namesake_alone():
    """A private sync whose filename collides with someone else's SHARED
    document must not claim it.

    The script writes an owner onto whatever it matches, so the wider
    "mine OR ownerless" scope would hand a document visible to the whole
    instance to the syncing user — silently, and without the
    knowledge:delete:anonymous check that deliberate shared deletion goes
    through. _indexed_shared_state cannot catch this: it keys on the connector
    file id, and a collision comes from a document this connector never
    ingested, so `shared` falls back to the sync's own private intent.
    """
    from utils.opensearch_queries import build_owned_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=False)
    processor.allow_anonymous_delete = False

    await processor._reconcile_shared_owner("report.pdf", False)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_owned_filename_query("report.pdf", "user-1")


@pytest.mark.asyncio
async def test_reconcile_with_permission_keeps_the_wider_scope():
    """Granted (and with RBAC unenforced, which resolves to granted), the
    reconcile still reaches ownerless chunks — the behaviour a shared re-sync
    relies on."""
    from utils.opensearch_queries import build_replace_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=False)
    processor.allow_anonymous_delete = True

    await processor._reconcile_shared_owner("report.pdf", False)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_replace_filename_query("report.pdf", "user-1")


@pytest.mark.asyncio
async def test_reconcile_of_a_shared_file_keeps_the_wider_scope():
    """A shared write cleared the permission upstream — connector_sync rejects a
    shared sync without it — so resolving to shared keeps the wider scope even
    when the flag is False."""
    from utils.opensearch_queries import build_replace_filename_query

    write_client = AsyncMock()
    settings_module.clients.opensearch = write_client

    processor = _make_processor(shared=True)
    processor.allow_anonymous_delete = False

    await processor._reconcile_shared_owner("report.pdf", True)

    query = write_client.update_by_query.await_args.kwargs["body"]["query"]
    assert query == build_replace_filename_query("report.pdf", "user-1")
