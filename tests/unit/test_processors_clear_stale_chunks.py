"""Re-indexing in `process_document_standard` must clear prior chunks for the
same `document_id` before writing the new ones.

Per-chunk indexing uses ids `{file_hash}_{i}` with `opensearch_client.index`
(upsert). Without a pre-delete, a re-index that produces fewer chunks than the
prior pass leaves trailing chunks `{file_hash}_{N..M-1}` behind with the OLD
metadata — most visibly, the old filename after a SharePoint rename. This test
pins the invariant introduced to fix that.

Pins: `src/models/processors.py` :: TaskProcessor.process_document_standard.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_processor_with_mocks():
    """Build a TaskProcessor wired to mocks for every external dependency
    `process_document_standard` reaches. Returns (processor, opensearch_client)."""
    from models.processors import TaskProcessor

    opensearch_client = AsyncMock()
    # exists() is checked at the top of process_document_standard; returning
    # False forces the re-index path (the path where delete_by_query must fire).
    opensearch_client.exists = AsyncMock(return_value=False)

    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    document_service = MagicMock()
    document_service.session_manager = session_manager

    models_service = MagicMock()
    models_service.get_litellm_model_name = AsyncMock(return_value="text-embedding-3-small")

    docling_service = MagicMock()  # unused for .txt path

    processor = TaskProcessor(
        document_service=document_service,
        models_service=models_service,
        docling_service=docling_service,
    )
    return processor, opensearch_client


def _patch_embedding_pipeline(monkeypatch, chunk_count: int):
    """Stub out the docling / embedding / index-mapping side of
    process_document_standard so the test focuses on the OpenSearch write
    ordering. `chunk_count` controls how many chunks the simulated text-file
    parse produces.
    """
    from models import processors as processors_mod

    fake_slim_doc = {
        "id": "doc",
        "filename": "ignored.txt",
        "mimetype": "text/plain",
        "chunks": [{"page": 1, "text": f"chunk-{i}"} for i in range(chunk_count)],
    }
    monkeypatch.setattr(processors_mod, "process_text_file", lambda _path: fake_slim_doc)

    # Embedding model resolution path (config + fallback).
    fake_config = MagicMock()
    fake_config.knowledge.embedding_model = "text-embedding-3-small"
    monkeypatch.setattr(processors_mod, "get_openrag_config", lambda: fake_config)
    monkeypatch.setattr(processors_mod, "get_embedding_model", lambda: "text-embedding-3-small")
    monkeypatch.setattr(processors_mod, "get_index_name", lambda: "test-index")

    # Field-mapping helper writes nothing useful for this test.
    async def _ensure_embedding_field_exists(_client, _model, _index, _dims):
        return "embedding_field"

    monkeypatch.setattr(
        processors_mod, "ensure_embedding_field_exists", _ensure_embedding_field_exists
    )

    # chunk_texts_for_embeddings is imported lazily inside the function from
    # services.document_service — patch it at its source.
    from services import document_service as ds_mod

    monkeypatch.setattr(
        ds_mod,
        "chunk_texts_for_embeddings",
        lambda texts, max_tokens=8000: [list(texts)],
    )

    # patched_embedding_client.embeddings.create — return one embedding per text.
    # `clients` is the singleton imported at module scope; replace it wholesale
    # (the real one's `patched_embedding_client` is a read-only @property).
    class _FakeEmbedResp:
        def __init__(self, n):
            self.data = [{"embedding": [0.1, 0.2, 0.3]} for _ in range(n)]

    fake_embed_client = MagicMock()
    fake_embed_client.embeddings.create = AsyncMock(
        side_effect=lambda model, input: _FakeEmbedResp(len(input))
    )
    fake_clients = MagicMock()
    fake_clients.patched_embedding_client = fake_embed_client
    monkeypatch.setattr(processors_mod, "clients", fake_clients)


@pytest.mark.asyncio
async def test_stale_chunks_cleared_before_reindex(monkeypatch):
    """Stale chunks must be cleared (via primary-id deletes) before any new
    `index()` call so prior chunks (e.g. with an old filename after a rename)
    cannot survive the per-chunk upsert.

    DLS-safe pattern: enumerate visible chunk _ids via search, then issue a
    `delete` per primary `_id`. `delete_by_query` is silently filtered under
    DLS and must NOT be used.
    """
    processor, opensearch_client = _make_processor_with_mocks()
    _patch_embedding_pipeline(monkeypatch, chunk_count=3)

    stale_chunk_ids = ["abc123_0", "abc123_1", "abc123_2", "abc123_3", "abc123_4"]
    op_order: list[tuple[str, dict]] = []

    async def _search(**kw):
        op_order.append(("search", kw))
        return {"_scroll_id": None, "hits": {"hits": [{"_id": cid} for cid in stale_chunk_ids]}}

    async def _delete(**kw):
        op_order.append(("delete", kw))
        return {"result": "deleted"}

    async def _index(**kw):
        op_order.append(("index", kw))

    opensearch_client.search = AsyncMock(side_effect=_search)
    opensearch_client.delete = AsyncMock(side_effect=_delete)
    opensearch_client.index = AsyncMock(side_effect=_index)

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"hello world")
        tmp_path = tmp.name

    try:
        await processor.process_document_standard(
            file_path=tmp_path,
            file_hash="abc123",
            owner_user_id="alice",
            original_filename="renamed.txt",
            connector_type="sharepoint",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    ops = [op for op, _ in op_order]
    assert ops, "process_document_standard wrote nothing — fixture is broken"

    # 1) The enumerate-via-search runs first.
    assert ops[0] == "search", f"search must run before deletes. Saw: {ops}"
    search_kwargs = op_order[0][1]
    assert search_kwargs["body"]["query"] == {"term": {"document_id": "abc123"}}
    assert search_kwargs["index"] == "test-index"

    # 2) All deletes complete BEFORE any index() — they must precede re-indexing.
    delete_indices = [i for i, op in enumerate(ops) if op == "delete"]
    index_indices = [i for i, op in enumerate(ops) if op == "index"]
    assert delete_indices, "no delete was issued; stale chunks would survive"
    assert index_indices, "no chunks were indexed"
    assert max(delete_indices) < min(index_indices), (
        f"all deletes must complete before any index(). Saw order: {ops}"
    )

    # 3) One primary-id delete per visible stale chunk, refresh=True.
    delete_calls = [kw for op, kw in op_order if op == "delete"]
    assert len(delete_calls) == len(stale_chunk_ids)
    for call, expected_id in zip(delete_calls, stale_chunk_ids, strict=True):
        assert call["index"] == "test-index"
        assert call["id"] == expected_id
        assert call.get("refresh") is True

    # 4) delete_by_query must NEVER be used (DLS would silently filter it).
    if hasattr(opensearch_client, "delete_by_query"):
        opensearch_client.delete_by_query.assert_not_called()


@pytest.mark.asyncio
async def test_delete_failure_does_not_abort_reindex(monkeypatch):
    """A transient delete failure must be logged and swallowed — the per-chunk
    upsert still runs so the sync isn't worse off than today's behavior."""
    processor, opensearch_client = _make_processor_with_mocks()
    _patch_embedding_pipeline(monkeypatch, chunk_count=2)

    # Have the enumerate step itself blow up — that's the only "delete failure"
    # surface the helper exposes, since per-id delete swallows NotFoundError.
    opensearch_client.search = AsyncMock(side_effect=RuntimeError("os 503"))
    opensearch_client.delete = AsyncMock()
    index_calls: list[dict] = []
    opensearch_client.index = AsyncMock(side_effect=lambda **kw: index_calls.append(kw))

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"hello world")
        tmp_path = tmp.name

    try:
        result = await processor.process_document_standard(
            file_path=tmp_path,
            file_hash="abc123",
            owner_user_id="alice",
            original_filename="renamed.txt",
            connector_type="sharepoint",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert result["status"] == "indexed"
    assert len(index_calls) == 2, "indexing must still happen if the pre-delete fails"


@pytest.mark.asyncio
async def test_connector_file_id_stored_in_chunk_when_provided(monkeypatch):
    """When connector_file_id is passed to process_document_standard, every
    indexed chunk must carry that value so the 404 cleanup path can find and
    delete chunks by their connector source ID."""
    processor, opensearch_client = _make_processor_with_mocks()
    _patch_embedding_pipeline(monkeypatch, chunk_count=2)

    opensearch_client.search = AsyncMock(return_value={"_scroll_id": None, "hits": {"hits": []}})
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
    indexed_bodies: list[dict] = []
    opensearch_client.index = AsyncMock(
        side_effect=lambda **kw: indexed_bodies.append(kw.get("body", {}))
    )

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"hello world")
        tmp_path = tmp.name

    try:
        result = await processor.process_document_standard(
            file_path=tmp_path,
            file_hash="sha-abc",
            owner_user_id="alice",
            original_filename="report.txt",
            connector_type="sharepoint",
            connector_file_id="sharepoint-item-xyz",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert result["status"] == "indexed"
    assert len(indexed_bodies) == 2, "expected one index call per chunk"
    for body in indexed_bodies:
        assert body.get("connector_file_id") == "sharepoint-item-xyz", (
            f"connector_file_id missing or wrong in chunk: {body}"
        )
        assert body.get("document_id") == "sha-abc", "document_id must still be the content hash"


@pytest.mark.asyncio
async def test_connector_file_id_absent_when_not_provided(monkeypatch):
    """When connector_file_id is not passed (local uploads, non-connector paths),
    the field must be absent from indexed chunks — no None/empty pollution."""
    processor, opensearch_client = _make_processor_with_mocks()
    _patch_embedding_pipeline(monkeypatch, chunk_count=1)

    opensearch_client.search = AsyncMock(return_value={"_scroll_id": None, "hits": {"hits": []}})
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})
    indexed_bodies: list[dict] = []
    opensearch_client.index = AsyncMock(
        side_effect=lambda **kw: indexed_bodies.append(kw.get("body", {}))
    )

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"hello world")
        tmp_path = tmp.name

    try:
        await processor.process_document_standard(
            file_path=tmp_path,
            file_hash="sha-xyz",
            owner_user_id="alice",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert len(indexed_bodies) == 1
    assert "connector_file_id" not in indexed_bodies[0]
