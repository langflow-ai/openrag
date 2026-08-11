"""Unit tests for two-slot chunk draft cache."""

from unittest.mock import AsyncMock

import pytest

from services.chunk_draft_service import ChunkDraftService, _chunk_from_hit
from utils.embedding_fields import get_embedding_field_name


def _hit(chunk_id: str, text: str, page: int = 1, model: str = "text-embedding-3-small"):
    field = get_embedding_field_name(model)
    return {
        "_id": chunk_id,
        "_source": {
            "text": text,
            "page": page,
            "document_id": "doc-1",
            "embedding_model": model,
            "embedding_dimensions": 3,
            field: [0.1, 0.2, 0.3],
            "metadata": {},
            "filename": "a.pdf",
        },
    }


def _search_response(hits: list[dict], total: int | None = None):
    return {
        "_scroll_id": "scroll-1",
        "hits": {
            "total": {"value": total if total is not None else len(hits)},
            "hits": hits,
        },
    }


def test_chunk_from_hit_loads_vector_and_text():
    chunk = _chunk_from_hit(_hit("id-0", "Hello world"))
    assert chunk.chunk_id == "id-0"
    assert chunk.text == "Hello world"
    assert chunk.vector == [0.1, 0.2, 0.3]
    assert chunk.embedding_model == "text-embedding-3-small"


@pytest.mark.asyncio
async def test_ensure_seeded_creates_original_and_last_changes():
    service = ChunkDraftService(ttl_seconds=300)
    client = AsyncMock()
    client.search = AsyncMock(
        return_value=_search_response([_hit("id-0", "A"), _hit("id-1", "B", page=2)])
    )
    client.clear_scroll = AsyncMock()

    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path="/tmp/a.pdf",
        document_id="doc-1",
        opensearch_client=client,
    )

    assert len(session.original) == 2
    assert len(session.last_changes) == 2
    assert len(session.baseline) == 2
    assert session.dirty is False
    assert session.chunks_truncated is False
    assert session.last_changes[0].text == "A"

    again = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path="/tmp/a.pdf",
        document_id="doc-1",
        opensearch_client=client,
    )
    assert again is session
    assert client.search.await_count == 1


@pytest.mark.asyncio
async def test_update_and_revert_draft():
    service = ChunkDraftService(ttl_seconds=300)
    client = AsyncMock()
    client.search = AsyncMock(return_value=_search_response([_hit("id-0", "Original")]))
    client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=client,
    )

    service.update_chunk_text(session, "id-0", "Edited")
    assert session.dirty is True
    assert session.last_changes[0].text == "Edited"
    assert session.original[0].text == "Original"
    assert session.last_changes[0].vector is None

    service.revert(session)
    assert session.dirty is False
    assert session.last_changes[0].text == "Original"
    assert session.last_changes[0].vector == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_delete_chunk_marks_dirty_and_blocks_last():
    service = ChunkDraftService(ttl_seconds=300)
    client = AsyncMock()
    client.search = AsyncMock(
        return_value=_search_response([_hit("id-0", "A"), _hit("id-1", "B")])
    )
    client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=client,
    )

    service.delete_chunk(session, "id-1")
    assert len(session.last_changes) == 1
    assert session.dirty is True

    with pytest.raises(ValueError, match="last remaining"):
        service.delete_chunk(session, "id-0")
    # Reject must not empty the session.
    assert len(session.last_changes) == 1
    assert session.last_changes[0].chunk_id == "id-0"


@pytest.mark.asyncio
async def test_commit_reembeds_dirty_and_deletes_removed(monkeypatch):
    service = ChunkDraftService(ttl_seconds=300)
    read_client = AsyncMock()
    read_client.search = AsyncMock(
        return_value=_search_response([_hit("id-0", "A"), _hit("id-1", "B")])
    )
    read_client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=read_client,
    )
    service.update_chunk_text(session, "id-0", "A-edited")
    service.delete_chunk(session, "id-1")

    write_client = AsyncMock()
    write_client.bulk = AsyncMock(return_value={"errors": False})

    async def fake_delete(*_args, **_kwargs):
        assert list(_kwargs["document_ids"]) == ["id-1"]
        return 1

    monkeypatch.setattr(
        "services.chunk_draft_service.delete_document_ids",
        fake_delete,
    )

    async def embed_texts(_model, texts):
        assert texts == ["A-edited"]
        return [[0.9, 0.8, 0.7]]

    result = await service.commit(
        session,
        opensearch_client=read_client,
        write_client=write_client,
        embed_texts=embed_texts,
    )

    assert result["committed"] is True
    assert result["deleted_stale"] == 1
    assert result["dirty"] is False
    assert result["modified_chunk_ids"] == ["id-0"]
    assert result["removed_chunk_ids"] == ["id-1"]
    assert session.last_changes[0].vector == [0.9, 0.8, 0.7]
    assert session.original[0].text == "A"
    assert len(session.original) == 2
    write_client.bulk.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_edit_only_does_not_delete_unknown_os_ids(monkeypatch):
    """Commit must not delete OpenSearch ids outside the seeded session."""
    service = ChunkDraftService(ttl_seconds=300)
    read_client = AsyncMock()
    read_client.search = AsyncMock(return_value=_search_response([_hit("id-0", "A")]))
    read_client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=read_client,
    )
    service.update_chunk_text(session, "id-0", "A-edited")

    write_client = AsyncMock()
    write_client.bulk = AsyncMock(return_value={"errors": False})
    deleted_ids: list[str] = []

    async def fake_delete(*_args, **_kwargs):
        deleted_ids.extend(list(_kwargs["document_ids"]))
        return len(_kwargs["document_ids"])

    monkeypatch.setattr(
        "services.chunk_draft_service.delete_document_ids",
        fake_delete,
    )

    async def embed_texts(_model, texts):
        return [[0.9, 0.8, 0.7]]

    result = await service.commit(
        session,
        opensearch_client=read_client,
        write_client=write_client,
        embed_texts=embed_texts,
    )

    assert result["committed"] is True
    assert result["modified_chunk_ids"] == ["id-0"]
    assert result["removed_chunk_ids"] == []
    assert deleted_ids == []
    assert result["deleted_stale"] == 0


@pytest.mark.asyncio
async def test_revert_after_commit_marks_unsaved(monkeypatch):
    service = ChunkDraftService(ttl_seconds=300)
    read_client = AsyncMock()
    read_client.search = AsyncMock(return_value=_search_response([_hit("id-0", "Original")]))
    read_client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=read_client,
    )
    service.update_chunk_text(session, "id-0", "Edited")

    write_client = AsyncMock()
    write_client.bulk = AsyncMock(return_value={"errors": False})

    async def fake_delete(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(
        "services.chunk_draft_service.delete_document_ids",
        fake_delete,
    )

    async def embed_texts(_model, texts):
        return [[0.9, 0.8, 0.7]]

    await service.commit(
        session,
        opensearch_client=read_client,
        write_client=write_client,
        embed_texts=embed_texts,
    )
    assert session.dirty is False
    assert session.baseline[0].text == "Edited"

    service.revert(session)
    assert session.last_changes[0].text == "Original"
    # OS still has Edited — user must be able to Confirm again.
    assert session.dirty is True


@pytest.mark.asyncio
async def test_seed_scrolls_all_pages():
    service = ChunkDraftService(ttl_seconds=300)
    client = AsyncMock()
    page1 = [_hit(f"id-{i}", f"t{i}") for i in range(200)]
    page2 = [_hit("id-200", "tail")]
    client.search = AsyncMock(
        return_value={
            "_scroll_id": "scroll-1",
            "hits": {"total": {"value": 201}, "hits": page1},
        }
    )
    client.scroll = AsyncMock(
        return_value={
            "_scroll_id": "scroll-1",
            "hits": {"total": {"value": 201}, "hits": page2},
        }
    )
    client.clear_scroll = AsyncMock()

    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=client,
    )

    assert len(session.last_changes) == 201
    assert session.chunks_truncated is False
    client.scroll.assert_awaited()
    client.clear_scroll.assert_awaited()
    search_body = client.search.await_args.kwargs["body"]
    assert search_body["sort"] == [{"page": "asc"}, {"_id": "asc"}]


@pytest.mark.asyncio
async def test_update_preserves_internal_whitespace():
    service = ChunkDraftService(ttl_seconds=300)
    client = AsyncMock()
    client.search = AsyncMock(return_value=_search_response([_hit("id-0", "A")]))
    client.clear_scroll = AsyncMock()
    session = await service.ensure_seeded(
        user_id="u1",
        task_id="t1",
        file_path=None,
        document_id="doc-1",
        opensearch_client=client,
    )
    service.update_chunk_text(session, "id-0", "  hello  world  ")
    assert session.last_changes[0].text == "  hello  world  "
