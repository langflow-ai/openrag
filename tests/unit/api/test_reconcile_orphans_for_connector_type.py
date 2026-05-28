"""Unit tests for `reconcile_orphans_for_connector_type` in `src/api/connectors.py`.

This is the orphan-deletion safety net for the connector sync flow. The
function must:
- Compute orphans = indexed_ids - union(remote_ids across all active
  connections of this connector_type for this user).
- Apply STRICT gating: any unauthenticated connection or listing
  exception aborts the pass with 0 deletes (false-negative > false-positive).
- Preserve files that exist in any active connection of the type
  (multi-connection isolation).
- Delete orphan chunks using the DLS-safe enumerate-then-delete pattern
  (NOT delete_by_query, which is silently no-opped under DLS).
- Query the correct OpenSearch field: connector_file_id for non-Langflow
  chunks, document_id for Langflow chunks.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_connection(connection_id: str, is_active: bool = True):
    return SimpleNamespace(connection_id=connection_id, is_active=is_active)


def _make_connector(remote_file_ids, *, authenticated=True, raise_on_list=False):
    connector = MagicMock()
    connector.is_authenticated = authenticated
    if raise_on_list:
        connector.list_files = AsyncMock(side_effect=RuntimeError("graph 503"))
    else:
        connector.list_files = AsyncMock(
            return_value={"files": [{"id": fid} for fid in remote_file_ids]}
        )
    return connector


def _make_service(connections, connector_lookup):
    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=connections)

    async def _get_connector(connection_id):
        return connector_lookup.get(connection_id)

    service.get_connector = AsyncMock(side_effect=_get_connector)
    return service


def _make_opensearch_client(chunk_ids: list[str] | None = None):
    """Build an OpenSearch mock wired for the enumerate-then-delete pattern.

    ``chunk_ids`` controls which chunk _ids the search returns (simulating
    what collect_visible_document_ids finds). Pass ``None`` or ``[]`` for
    "no chunks found" (no-orphan scenarios).
    """
    client = AsyncMock()
    hits = [{"_id": cid} for cid in (chunk_ids or [])]
    client.search = AsyncMock(return_value={"_scroll_id": None, "hits": {"hits": hits}})
    client.delete = AsyncMock(return_value={"result": "deleted"})
    return client


def _make_session_manager(opensearch_client):
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    return sm


# ---------------------------------------------------------------------------
# Gating / no-op scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_existing_file_ids_returns_empty_without_calls():
    from api.connectors import reconcile_orphans_for_connector_type

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock()
    sm = _make_session_manager(AsyncMock())

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=[],
    )

    assert result == []
    service.connection_manager.list_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_active_connections_skips_reconcile():
    from api.connectors import reconcile_orphans_for_connector_type

    inactive = [_make_connection("c1", is_active=False)]
    service = _make_service(inactive, connector_lookup={})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthenticated_connection_aborts_pass():
    """STRICT GATING: even one unauthenticated connector aborts the pass."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    connector.list_files.assert_not_awaited()
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_listing_exception_aborts_pass():
    """STRICT GATING: a transient list_files error aborts the pass."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], raise_on_list=True)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_orphans_skips_delete_call():
    """If every indexed ID still exists remotely, no delete must be issued."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "b"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Happy path (DLS-safe enumerate-then-delete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_deletes_orphans():
    """Indexed has [a, b, c]; remote has [a, c] → orphan = [b].

    The implementation must use the DLS-safe pattern: enumerate visible chunk
    _ids via search, then issue one primary-id delete per chunk. delete_by_query
    must NEVER be called (silently no-opped under DLS).
    """
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "c"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    # One chunk belongs to orphan "b"
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-b-0"])
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert result == ["b"]

    # DLS-safe: must NOT call delete_by_query
    opensearch_client.delete_by_query.assert_not_called()

    # Must enumerate via search first…
    opensearch_client.search.assert_awaited_once()
    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"document_id": ["b"]}}

    # …then delete each chunk by primary _id
    opensearch_client.delete.assert_awaited_once()
    delete_kwargs = opensearch_client.delete.await_args.kwargs
    assert delete_kwargs["id"] == "chunk-b-0"
    assert delete_kwargs.get("refresh") is True


@pytest.mark.asyncio
async def test_delete_failure_does_not_raise():
    """If the bulk delete blows up, the helper must swallow it (no exception).
    The function still returns the orphan IDs that were identified — callers
    use the return value to know *what* was orphaned, not whether deletion
    succeeded."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a"])
    service = _make_service([conn], connector_lookup={"c1": connector})

    opensearch_client = AsyncMock()
    # Make the search call itself fail so delete_chunks_by_document_ids raises
    opensearch_client.search = AsyncMock(side_effect=RuntimeError("opensearch unavailable"))
    sm = _make_session_manager(opensearch_client)

    # Must not raise even though deletion fails
    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    # "b" was identified as orphaned; deletion failed silently
    assert result == ["b"]


# ---------------------------------------------------------------------------
# Multi-connection isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_connection_union_preserves_files_present_in_any_connection():
    """conn-A has [a]. conn-B has [b]. Both [a, b] must be preserved."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=["b"])
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_connection_one_offline_aborts_even_if_other_succeeds():
    """conn-B unauthenticated — must abort even though conn-A succeeded."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert result == []
    opensearch_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_paginated_listing_aggregates_all_pages():
    """Remote listings are paginated — must walk every page."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = MagicMock()
    connector.is_authenticated = True
    pages = [
        {"files": [{"id": "a"}], "nextPageToken": "tok-1"},
        {"files": [{"id": "b"}, {"id": "c"}]},
    ]
    connector.list_files = AsyncMock(side_effect=pages)

    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client()
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert result == []
    assert connector.list_files.await_count == 2
    opensearch_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# id_field routing — connector_file_id vs document_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connector_file_id_field_used_when_specified():
    """When id_field='connector_file_id', the delete query must target that
    field. This is the non-Langflow (DISABLE_INGEST_WITH_LANGFLOW=True) path
    where chunks carry document_id=SHA_hash but connector_file_id=connector_ID.
    """
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    # Remote only has "sp-guid-a"; "sp-guid-b" is orphaned
    connector = _make_connector(remote_file_ids=["sp-guid-a"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-b-0", "chunk-b-1"])
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["sp-guid-a", "sp-guid-b"],
        id_field="connector_file_id",
    )

    assert result == ["sp-guid-b"]

    opensearch_client.delete_by_query.assert_not_called()

    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"connector_file_id": ["sp-guid-b"]}}, (
        f"Expected connector_file_id query, got: {search_body['query']}"
    )

    assert opensearch_client.delete.await_count == 2


@pytest.mark.asyncio
async def test_document_id_field_used_by_default():
    """Default id_field='document_id' preserves the Langflow path behavior
    where document_id already holds the connector source ID.
    """
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["lf-id-a"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = _make_opensearch_client(chunk_ids=["chunk-lf-b-0"])
    sm = _make_session_manager(opensearch_client)

    result = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["lf-id-a", "lf-id-b"],
        # id_field defaults to "document_id"
    )

    assert result == ["lf-id-b"]

    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["query"] == {"terms": {"document_id": ["lf-id-b"]}}, (
        f"Expected document_id query, got: {search_body['query']}"
    )
