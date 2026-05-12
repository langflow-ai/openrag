"""Unit tests for `reconcile_orphans_for_connector_type` in `src/api/connectors.py`.

This is the orphan-deletion safety net for the connector sync flow. The
function must:
- Compute orphans = indexed_ids - union(remote_ids across all active
  connections of this connector_type for this user).
- Apply STRICT gating: any unauthenticated connection or listing
  exception aborts the pass with 0 deletes (false-negative > false-positive).
- Preserve files that exist in any active connection of the type
  (multi-connection isolation).
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
    """Lightweight stand-in for ConnectionConfig — only the attributes
    reconcile_orphans_for_connector_type reads."""
    return SimpleNamespace(connection_id=connection_id, is_active=is_active)


def _make_connector(remote_file_ids, *, authenticated=True, raise_on_list=False):
    """Build an AsyncMock connector that reports the given file IDs from
    list_files() (single page, no pagination)."""
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
    """Build a connector_service stub.

    `connections` is the list returned by list_connections.
    `connector_lookup` maps connection_id -> connector mock (or None).
    """
    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock(return_value=connections)

    async def _get_connector(connection_id):
        return connector_lookup.get(connection_id)

    service.get_connector = AsyncMock(side_effect=_get_connector)
    return service


def _make_session_manager(opensearch_client):
    sm = MagicMock()
    sm.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    return sm


@pytest.mark.asyncio
async def test_empty_existing_file_ids_returns_zero_without_calls():
    from api.connectors import reconcile_orphans_for_connector_type

    service = MagicMock()
    service.connection_manager = MagicMock()
    service.connection_manager.list_connections = AsyncMock()
    sm = _make_session_manager(AsyncMock())

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=[],
    )

    assert deleted == 0
    service.connection_manager.list_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_active_connections_skips_reconcile():
    """If every connection is inactive, we have no remote view — skip."""
    from api.connectors import reconcile_orphans_for_connector_type

    inactive = [_make_connection("c1", is_active=False)]
    service = _make_service(inactive, connector_lookup={})
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthenticated_connection_aborts_pass(monkeypatch):
    """STRICT GATING: even one unauthenticated connector aborts the pass.
    Otherwise we'd wrongly mark a file as an orphan because we couldn't
    list the connection that holds it."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
    connector.list_files.assert_not_awaited()
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_listing_exception_aborts_pass():
    """STRICT GATING: a transient list_files error aborts the pass.
    Better to leave orphans for one cycle than delete legitimate files."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=[], raise_on_list=True)
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_happy_path_deletes_orphans():
    """Indexed has [a, b, c]; remote has [a, c] -> orphan = [b]."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "c"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = AsyncMock()
    opensearch_client.delete_by_query.return_value = {"deleted": 7}
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert deleted == 7
    opensearch_client.delete_by_query.assert_awaited_once()
    body = opensearch_client.delete_by_query.await_args.kwargs["body"]
    assert body == {"query": {"terms": {"document_id": ["b"]}}}


@pytest.mark.asyncio
async def test_no_orphans_skips_delete_call():
    """If every indexed ID still exists remotely, we must not issue an
    empty delete_by_query."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a", "b"])
    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_connection_union_preserves_files_present_in_any_connection():
    """Multi-connection isolation:
    - User has conn-A and conn-B (both SharePoint, different sites).
    - Indexed has [a, b]. conn-A has [a]. conn-B has [b].
    - Neither file is an orphan — both should be preserved."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=["b"])
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_connection_one_offline_aborts_even_if_other_succeeds():
    """If conn-A lists fine but conn-B is unauthenticated, we MUST NOT
    treat files only in conn-B as orphans. Strict gating bails out."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn_a = _make_connection("conn-a")
    conn_b = _make_connection("conn-b")
    connector_a = _make_connector(remote_file_ids=["a"])
    connector_b = _make_connector(remote_file_ids=[], authenticated=False)
    service = _make_service(
        [conn_a, conn_b],
        connector_lookup={"conn-a": connector_a, "conn-b": connector_b},
    )
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],  # b would look like an orphan if we trusted conn-A alone
    )

    assert deleted == 0
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_paginated_listing_aggregates_all_pages():
    """Remote listings are paginated. The reconcile must walk every page
    before computing the orphan set, otherwise files on page 2 look like
    orphans."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = MagicMock()
    connector.is_authenticated = True
    pages = [
        {"files": [{"id": "a"}], "nextPageToken": "tok-1"},
        {"files": [{"id": "b"}, {"id": "c"}]},  # last page, no token
    ]
    connector.list_files = AsyncMock(side_effect=pages)

    service = _make_service([conn], connector_lookup={"c1": connector})
    opensearch_client = AsyncMock()
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b", "c"],
    )

    assert deleted == 0
    assert connector.list_files.await_count == 2
    opensearch_client.delete_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_failure_does_not_raise():
    """If the bulk delete itself blows up, the helper must swallow it and
    return 0. The caller (sync) should still proceed to re-sync surviving
    files — leaving orphans is recoverable, raising is not."""
    from api.connectors import reconcile_orphans_for_connector_type

    conn = _make_connection("c1")
    connector = _make_connector(remote_file_ids=["a"])
    service = _make_service([conn], connector_lookup={"c1": connector})

    opensearch_client = AsyncMock()
    opensearch_client.delete_by_query.side_effect = RuntimeError("opensearch unavailable")
    sm = _make_session_manager(opensearch_client)

    deleted = await reconcile_orphans_for_connector_type(
        connector_type="sharepoint",
        user_id="alice",
        connector_service=service,
        session_manager=sm,
        jwt_token=None,
        existing_file_ids=["a", "b"],
    )

    assert deleted == 0
