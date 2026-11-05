"""Chunk stats computed from the chunks a file left in the index."""

import pytest

from services.chunk_stats import compute_chunk_stats
from utils.document_processing import IMAGE_PLACEHOLDER


def _chunk(text, page=1, **fields):
    return {"text": text, "page": page, **fields}


def _by_words(text):
    return len(text.split())


def test_lengths_are_summarised_in_characters_and_tokens():
    chunks = [_chunk("a" * n + " b" * n) for n in range(1, 11)]

    stats = compute_chunk_stats(chunks, ingest_path="openrag", count_tokens=_by_words)

    assert stats["chunk_count"] == 10
    # Chunk n is 3n characters and n + 1 words.
    assert stats["chars"] == {"min": 3, "median": 16.5, "p90": 27, "max": 30}
    assert stats["tokens"] == {"min": 2, "median": 6.5, "p90": 10, "max": 11}


def test_chunks_per_page():
    chunks = [_chunk("x", page=1), _chunk("x", page=1), _chunk("x", page=1), _chunk("x", page=2)]

    stats = compute_chunk_stats(chunks, ingest_path="openrag", count_tokens=_by_words)

    assert stats["pages"] == {
        "count": 2,
        "chunks_per_page": {"min": 1, "median": 2, "p90": 3, "max": 3},
    }


def test_chunks_without_a_page_are_left_out_of_the_page_counts():
    chunks = [_chunk("x", page=None), _chunk("x", page=3)]

    stats = compute_chunk_stats(chunks, ingest_path="langflow", count_tokens=_by_words)

    assert stats["pages"] == {
        "count": 1,
        "chunks_per_page": {"min": 1, "median": 1, "p90": 1, "max": 1},
    }


def test_empty_and_placeholder_chunks_are_counted():
    chunks = [
        _chunk("real text"),
        _chunk(""),
        _chunk("   \n"),
        _chunk(IMAGE_PLACEHOLDER),
        _chunk(f"  {IMAGE_PLACEHOLDER}\n"),
    ]

    stats = compute_chunk_stats(chunks, ingest_path="openrag", count_tokens=_by_words)

    assert stats["empty_chunks"] == 2
    assert stats["placeholder_chunks"] == 2


def test_an_image_only_document_is_all_placeholders():
    chunks = [_chunk(IMAGE_PLACEHOLDER, page=p) for p in (1, 2)]

    stats = compute_chunk_stats(chunks, ingest_path="langflow", count_tokens=_by_words)

    assert stats["chunk_count"] == 2
    assert stats["placeholder_chunks"] == 2
    assert stats["empty_chunks"] == 0


def test_no_chunks():
    stats = compute_chunk_stats([], ingest_path="openrag", count_tokens=_by_words)

    assert stats == {
        "ingest_path": "openrag",
        "chunk_count": 0,
        "chars": None,
        "tokens": None,
        "pages": {"count": 0, "chunks_per_page": None},
        "empty_chunks": 0,
        "placeholder_chunks": 0,
        "parser": None,
        "chunk_size": None,
        "chunk_overlap": None,
        "embedding_model": None,
    }


def test_settings_are_read_from_chunk_metadata():
    chunks = [
        _chunk(
            "x",
            parser="Docling Serve 1.20.0",
            chunk_size=1000,
            chunk_overlap=200,
            embedding_model="text-embedding-3-small",
        ),
        _chunk(
            "y",
            parser="Docling Serve 1.20.0",
            chunk_size=1000,
            chunk_overlap=200,
            embedding_model="text-embedding-3-small",
        ),
    ]

    stats = compute_chunk_stats(chunks, ingest_path="langflow", count_tokens=_by_words)

    assert stats["ingest_path"] == "langflow"
    assert stats["parser"] == "Docling Serve 1.20.0"
    assert stats["chunk_size"] == 1000
    assert stats["chunk_overlap"] == 200
    assert stats["embedding_model"] == "text-embedding-3-small"


def test_settings_that_differ_between_chunks_are_all_listed():
    chunks = [_chunk("x", chunk_size=1000), _chunk("y", chunk_size=500), _chunk("z")]

    stats = compute_chunk_stats(chunks, ingest_path="openrag", count_tokens=_by_words)

    assert stats["chunk_size"] == [500, 1000]


def test_tokens_default_to_the_embedding_models_tokenizer():
    chunks = [_chunk("hello world", embedding_model="text-embedding-3-small")]

    stats = compute_chunk_stats(chunks, ingest_path="openrag")

    assert stats["tokens"]["max"] == 2


def test_an_unknown_model_falls_back_to_cl100k():
    chunks = [_chunk("hello world", embedding_model="ibm/granite-embedding-278m")]

    stats = compute_chunk_stats(chunks, ingest_path="openrag")

    assert stats["tokens"]["max"] == 2


def _client(hits, total=None):
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.search.return_value = {
        "hits": {
            "hits": [{"_id": f"c{i}", "_source": source} for i, source in enumerate(hits)],
            "total": {"value": len(hits) if total is None else total},
        }
    }
    return client


@pytest.mark.asyncio
async def test_collect_reads_the_documents_chunks_from_the_index():
    from services.chunk_stats import STATS_MAX_CHUNKS, collect_chunk_stats

    client = _client([{"text": "hello world", "page": 1}, {"text": "bye", "page": 2}])

    stats = await collect_chunk_stats(
        client, ingest_run_id="run-1", ingest_path="openrag", index_name="documents"
    )

    # Chunks written moments ago are searchable only after a refresh.
    client.indices.refresh.assert_awaited_once_with(index="documents")
    search = client.search.await_args.kwargs
    assert search["index"] == "documents"
    assert search["body"]["query"] == {"term": {"ingest_run_id": "run-1"}}
    assert search["body"]["size"] == STATS_MAX_CHUNKS
    assert search["body"]["track_total_hits"] is True
    assert set(search["body"]["_source"]["includes"]) == {
        "text",
        "page",
        "parser",
        "chunk_size",
        "chunk_overlap",
        "embedding_model",
    }
    assert stats["chunk_count"] == 2
    assert stats["pages"]["count"] == 2
    assert stats["truncated"] is False


@pytest.mark.asyncio
async def test_collect_says_when_the_document_has_more_chunks_than_it_read():
    from services.chunk_stats import collect_chunk_stats

    client = _client([{"text": "x", "page": 1}], total=12_000)

    stats = await collect_chunk_stats(
        client, ingest_run_id="run-1", ingest_path="openrag", index_name="documents"
    )

    assert stats["chunk_count"] == 1
    assert stats["truncated"] is True
    assert stats["indexed_chunk_count"] == 12_000


def _file_task(result, document_id=None):
    from models.tasks import FileTask, TaskStatus

    task = FileTask(file_path="/data/a.pdf", filename="a.pdf", document_id=document_id)
    task.status = TaskStatus.COMPLETED
    task.result = result
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize("ingest_path", ["openrag", "langflow"])
async def test_an_ingested_file_gets_chunk_stats_in_its_result(ingest_path):
    from services.chunk_stats import record_chunk_stats

    client = _client([{"text": "hello", "page": 1}])
    task = _file_task(
        {"status": "indexed", "id": "hash-1", "ingest_path": ingest_path, "ingest_run_id": "run-1"}
    )

    await record_chunk_stats(task, client=client)

    assert client.search.await_args.kwargs["body"]["query"] == {"term": {"ingest_run_id": "run-1"}}
    assert task.result["status"] == "indexed"
    assert task.result["chunk_stats"]["chunk_count"] == 1
    assert task.result["chunk_stats"]["ingest_path"] == ingest_path


@pytest.mark.asyncio
async def test_collect_can_skip_the_refresh():
    from services.chunk_stats import collect_chunk_stats

    client = _client([{"text": "x", "page": 1}])

    await collect_chunk_stats(
        client, ingest_run_id="run-1", ingest_path="openrag", index_name="documents", refresh=False
    )

    client.indices.refresh.assert_not_awaited()
    client.search.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("ingest_path", "refreshed"), [("openrag", False), ("langflow", True)])
async def test_only_langflow_ingests_refresh_before_reading_stats(ingest_path, refreshed):
    """The OpenRAG writer refreshes on its final batch; Langflow's writes aren't refreshed."""
    from services.chunk_stats import record_chunk_stats

    client = _client([{"text": "hello", "page": 1}])
    task = _file_task(
        {"status": "indexed", "id": "hash-1", "ingest_path": ingest_path, "ingest_run_id": "run-1"}
    )

    await record_chunk_stats(task, client=client)

    assert client.indices.refresh.await_count == (1 if refreshed else 0)


def _index(chunks):
    """A client whose search applies the query's ``ingest_run_id`` term to ``chunks``."""
    from unittest.mock import AsyncMock

    client = AsyncMock()

    async def search(index, body):
        run_id = body["query"]["term"]["ingest_run_id"]
        hits = [c for c in chunks if c.get("ingest_run_id") == run_id]
        return {"hits": {"hits": [{"_source": c} for c in hits], "total": {"value": len(hits)}}}

    client.search.side_effect = search
    return client


@pytest.mark.asyncio
async def test_only_the_files_own_ingest_run_is_counted():
    """Another user's private copy, or an earlier run's leftovers, share the
    document_id but not the run."""
    from services.chunk_stats import record_chunk_stats

    client = _index(
        [
            {"document_id": "hash-1", "ingest_run_id": "run-1", "text": "mine"},
            {"document_id": "hash-1", "ingest_run_id": "run-other", "text": "theirs"},
            {"document_id": "hash-1", "ingest_run_id": "run-other", "text": "theirs too"},
        ]
    )
    task = _file_task(
        {"status": "indexed", "id": "hash-1", "ingest_path": "openrag", "ingest_run_id": "run-1"}
    )

    await record_chunk_stats(task, client=client)

    assert task.result["chunk_stats"]["chunk_count"] == 1


@pytest.mark.asyncio
async def test_a_result_without_an_ingest_run_gets_no_stats():
    """Langflow without the ingest callback writes directly and leaves no run id."""
    from services.chunk_stats import record_chunk_stats

    client = _client([{"text": "hello", "page": 1}])
    result = {"status": "success", "ingest_path": "langflow", "ingest_run_id": None}
    task = _file_task(dict(result), document_id="hash-1")

    await record_chunk_stats(task, client=client)

    client.search.assert_not_awaited()
    assert task.result == result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"status": "unchanged", "id": "hash-1"},
        {"status": "skipped", "reason": "duplicate_content", "document_id": "hash-1"},
        {"status": "completed", "reason": "deleted_at_source", "deleted_chunks": 3},
        None,
    ],
)
async def test_files_that_were_not_ingested_get_no_stats(result):
    from services.chunk_stats import record_chunk_stats

    client = _client([])
    task = _file_task(result, document_id="hash-1")

    await record_chunk_stats(task, client=client)

    client.search.assert_not_awaited()
    assert task.result == result


@pytest.mark.asyncio
async def test_a_failed_file_gets_no_stats():
    from models.tasks import TaskStatus
    from services.chunk_stats import record_chunk_stats

    client = _client([])
    task = _file_task(
        {"status": "indexed", "id": "hash-1", "ingest_path": "openrag", "ingest_run_id": "run-1"}
    )
    task.status = TaskStatus.FAILED

    await record_chunk_stats(task, client=client)

    client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stats_failure_is_logged_and_the_file_keeps_its_result():
    from models.tasks import TaskStatus
    from services.chunk_stats import record_chunk_stats

    client = _client([])
    client.search.side_effect = RuntimeError("opensearch down")
    result = {
        "status": "indexed",
        "id": "hash-1",
        "ingest_path": "openrag",
        "ingest_run_id": "run-1",
    }
    task = _file_task(dict(result))

    await record_chunk_stats(task, client=client)

    assert task.status == TaskStatus.COMPLETED
    assert task.result == result


@pytest.mark.asyncio
async def test_no_index_client_means_no_stats(monkeypatch):
    from config.settings import clients
    from services.chunk_stats import record_chunk_stats

    monkeypatch.setattr(clients, "opensearch", None)
    result = {
        "status": "indexed",
        "id": "hash-1",
        "ingest_path": "openrag",
        "ingest_run_id": "run-1",
    }
    task = _file_task(dict(result))

    await record_chunk_stats(task)

    assert task.result == result
