"""Contract of connectors.chunk_cleanup — the single deletion path for a
connector file's indexed chunks (orphan reconcile, 404 cleanup, rename
cleanup all go through it).

- empty input is a no-op (no OpenSearch call)
- the query matches BOTH id layouts (document_id and connector_file_id)
- DLS-safe: visible chunk _ids are enumerated with the caller's client, then
  deleted one-by-one by primary id with the trusted backend write client
  (`delete_by_query` is silently filtered under DLS)
- owner/shared scoping and rename keep_filenames shape the query
"""

from unittest.mock import AsyncMock

import pytest

from connectors.chunk_cleanup import (
    build_connector_file_chunks_query,
    delete_connector_file_chunks,
)


@pytest.fixture
def write_client(monkeypatch):
    import config.settings as cfg

    client = AsyncMock()
    client.delete = AsyncMock(return_value={"result": "deleted"})
    monkeypatch.setattr(cfg.clients, "opensearch", client)
    return client


def _id_terms(query) -> dict:
    shoulds = query["bool"]["filter"][0]["bool"]["should"]
    return {next(iter(c["terms"])): next(iter(c["terms"].values())) for c in shoulds}


def test_query_matches_both_id_fields():
    query = build_connector_file_chunks_query(["file-1", "file-2"])
    fields = _id_terms(query)
    assert fields == {
        "document_id": ["file-1", "file-2"],
        "connector_file_id": ["file-1", "file-2"],
        "connector_file_id.keyword": ["file-1", "file-2"],
    }
    assert query["bool"]["filter"][0]["bool"]["minimum_should_match"] == 1


def test_query_owner_scoping():
    query = build_connector_file_chunks_query(["f"], owner_user_id="alice")
    assert {"term": {"owner": "alice"}} in query["bool"]["filter"]


def test_query_shared_targets_ownerless_chunks():
    query = build_connector_file_chunks_query(["f"], owner_user_id="alice", shared=True)
    assert {"bool": {"must_not": {"exists": {"field": "owner"}}}} in query["bool"]["filter"]
    assert {"term": {"owner": "alice"}} not in query["bool"]["filter"]


def test_query_keep_filenames_excluded():
    query = build_connector_file_chunks_query(["f"], keep_filenames=["new.pdf", "new_.pdf"])
    assert query["bool"]["must_not"] == [{"terms": {"filename": ["new.pdf", "new_.pdf"]}}]


def test_query_unscoped_when_no_owner():
    query = build_connector_file_chunks_query(["f"])
    assert len(query["bool"]["filter"]) == 1
    assert "must_not" not in query["bool"]


def test_query_connector_type_filter():
    query = build_connector_file_chunks_query(["f"], connector_type="ibm_cos")
    assert {"term": {"connector_type": "ibm_cos"}} in query["bool"]["filter"]


def test_query_connector_type_with_private_owner():
    query = build_connector_file_chunks_query(
        ["f"], connector_type="google_drive", owner_user_id="alice"
    )
    filters = query["bool"]["filter"]
    assert {"term": {"connector_type": "google_drive"}} in filters
    assert {"term": {"owner": "alice"}} in filters


def test_query_connector_type_with_shared_scope():
    query = build_connector_file_chunks_query(["f"], connector_type="ibm_cos", shared=True)
    filters = query["bool"]["filter"]
    assert {"term": {"connector_type": "ibm_cos"}} in filters
    assert {"bool": {"must_not": {"exists": {"field": "owner"}}}} in filters
    assert {"term": {"owner": "alice"}} not in filters


def test_query_no_connector_type_when_none():
    query = build_connector_file_chunks_query(["f"])
    for f in query["bool"]["filter"]:
        if "term" in f:
            assert "connector_type" not in f["term"]


@pytest.mark.asyncio
async def test_empty_ids_short_circuit_without_calling_opensearch(write_client):
    opensearch_client = AsyncMock()

    deleted = await delete_connector_file_chunks([], opensearch_client)

    assert deleted == 0
    opensearch_client.search.assert_not_awaited()
    write_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_deletes_each_visible_chunk_id_by_primary_id(write_client, monkeypatch):
    """Visible chunk _ids are enumerated with the caller's client and deleted
    one-by-one via the backend write client. delete_by_query is forbidden —
    DLS / certain security plugins silently no-op it."""
    monkeypatch.setattr("config.settings.get_index_name", lambda: "test-index")

    opensearch_client = AsyncMock()
    chunk_ids = ["chunk-1", "chunk-2", "chunk-3"]
    opensearch_client.search.return_value = {
        "_scroll_id": None,
        "hits": {"hits": [{"_id": cid} for cid in chunk_ids]},
    }

    deleted = await delete_connector_file_chunks(
        ["doc-a", "doc-b"], opensearch_client, refresh=True
    )

    assert deleted == len(chunk_ids)
    opensearch_client.delete_by_query.assert_not_awaited()
    write_client.delete_by_query.assert_not_awaited()

    search_call = opensearch_client.search.await_args
    assert search_call.kwargs["index"] == "test-index"
    fields = _id_terms(search_call.kwargs["body"]["query"])
    assert fields["document_id"] == ["doc-a", "doc-b"]
    assert fields["connector_file_id"] == ["doc-a", "doc-b"]
    assert fields["connector_file_id.keyword"] == ["doc-a", "doc-b"]

    opensearch_client.delete.assert_not_awaited()
    delete_calls = write_client.delete.await_args_list
    assert [call.kwargs["id"] for call in delete_calls] == chunk_ids
    for call in delete_calls:
        assert call.kwargs["index"] == "test-index"
        assert call.kwargs.get("refresh") is True


@pytest.mark.asyncio
async def test_returns_zero_when_no_visible_chunks_match(write_client):
    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {"_scroll_id": None, "hits": {"hits": []}}

    deleted = await delete_connector_file_chunks(["abc"], opensearch_client)

    assert deleted == 0
    write_client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_raises_when_write_client_unavailable(monkeypatch):
    import config.settings as cfg

    monkeypatch.setattr(cfg.clients, "opensearch", None)
    with pytest.raises(RuntimeError, match="write client"):
        await delete_connector_file_chunks(["abc"], AsyncMock())
