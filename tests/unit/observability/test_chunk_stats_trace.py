"""A file's chunk stats reach Langfuse as their own trace in the task's session."""

from unittest.mock import AsyncMock

import pytest
from langfuse._client.attributes import LangfuseOtelSpanAttributes as LF

from models.tasks import FileTask, TaskStatus
from observability.tracing import trace_context
from services.chunk_stats import record_chunk_stats


def _metadata(span, key):
    return span.attributes.get(f"{LF.OBSERVATION_METADATA}.openrag.{key}")


def _trace_metadata(span, key):
    return span.attributes.get(f"{LF.TRACE_METADATA}.openrag.{key}")


def _client(sources):
    client = AsyncMock()
    client.search.return_value = {
        "hits": {
            "hits": [{"_id": f"c{i}", "_source": s} for i, s in enumerate(sources)],
            "total": {"value": len(sources)},
        }
    }
    return client


def _file_task(ingest_path="langflow"):
    task = FileTask(file_path="/data/a.pdf", filename="a.pdf", document_id="hash-1")
    task.status = TaskStatus.COMPLETED
    task.result = {"status": "success", "ingest_path": ingest_path}
    return task


@pytest.mark.asyncio
async def test_stats_are_traced_in_the_tasks_session(finished):
    client = _client(
        [
            {"text": "secret chunk text", "page": 1, "chunk_size": 1000},
            {"text": "more secret text", "page": 2, "chunk_size": 1000},
        ]
    )

    with trace_context(session_id="task-9", attributes={"openrag.task_id": "task-9"}):
        await record_chunk_stats(_file_task(), client=client)

    root = finished()["ingest.chunk_stats"]
    assert root.attributes[LF.TRACE_SESSION_ID] == "task-9"
    assert _trace_metadata(root, "task_id") == "task-9"
    assert _trace_metadata(root, "document_id") == "hash-1"
    assert _trace_metadata(root, "ingest_path") == "langflow"
    assert _metadata(root, "chunk_stats.chunk_count") == 2
    assert _metadata(root, "chunk_stats.chars.max") == 17
    assert _metadata(root, "chunk_stats.pages.count") == 2
    assert _metadata(root, "chunk_stats.chunk_size") == 1000
    assert "secret" not in str(root.attributes)


@pytest.mark.asyncio
async def test_a_stats_failure_is_traced_as_an_error(finished):
    client = _client([])
    client.search.side_effect = RuntimeError("index says: secret chunk text")

    await record_chunk_stats(_file_task(), client=client)

    root = finished()["ingest.chunk_stats"]
    assert root.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert "secret" not in str(root.attributes)
