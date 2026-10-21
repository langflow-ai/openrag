"""Summary stats over the chunks a file left in the index.

Computed from what landed in OpenSearch rather than from either pipeline's
internals, so Langflow and non-Langflow ingests are measured the same way and
can be compared.
"""

import asyncio
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from config.settings import clients, get_index_name
from models.tasks import FileTask, TaskStatus
from observability.spans import trace_root
from services.ingest_preview_service import document_chunks_query
from utils.document_processing import IMAGE_PLACEHOLDER
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Chunk fields that record how a file was ingested, written by both paths.
SETTING_FIELDS = ("parser", "chunk_size", "chunk_overlap", "embedding_model")

# One search page; OpenSearch's default ``index.max_result_window``.
STATS_MAX_CHUNKS = 10_000

# Stats are a side measurement: never hold a file's task open long for them.
STATS_TIMEOUT_SECONDS = 30


def _summary(values: list[int]) -> dict[str, float] | None:
    """min / median / p90 (nearest rank) / max, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p90": ordered[math.ceil(0.9 * len(ordered)) - 1],
        "max": ordered[-1],
    }


def _setting(chunks: list[dict[str, Any]], field: str) -> Any:
    """The chunks' value for ``field``; a sorted list when they disagree."""
    values = {chunk[field] for chunk in chunks if chunk.get(field) is not None}
    if not values:
        return None
    if len(values) == 1:
        return values.pop()
    try:
        return sorted(values)
    except TypeError:  # mixed types, e.g. 1000 and "1000"
        return sorted(values, key=str)


def _tiktoken_counter(model: str | None) -> Callable[[str], int]:
    """Token count by the embedding model's tokenizer, else ``cl100k_base``.

    The same rule as ``split_chunks_by_max_tokens``, so for models tiktoken
    doesn't know it is an approximation.
    """
    import tiktoken

    try:
        encoding = tiktoken.encoding_for_model(model) if model else None
    except KeyError:
        encoding = None
    encoding = encoding or tiktoken.get_encoding("cl100k_base")
    return lambda text: len(encoding.encode(text, disallowed_special=()))


def compute_chunk_stats(
    chunks: Iterable[dict[str, Any]],
    *,
    ingest_path: str,
    count_tokens: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Stats over indexed chunks (dicts with ``text``, ``page`` and the setting fields)."""
    chunks = list(chunks)
    settings = {field: _setting(chunks, field) for field in SETTING_FIELDS}
    if count_tokens is None:
        model = settings["embedding_model"]
        count_tokens = _tiktoken_counter(model if isinstance(model, str) else None)

    texts = [chunk.get("text") or "" for chunk in chunks]
    per_page = Counter(chunk["page"] for chunk in chunks if chunk.get("page") is not None)
    return {
        "ingest_path": ingest_path,
        "chunk_count": len(chunks),
        "chars": _summary([len(text) for text in texts]),
        "tokens": _summary([count_tokens(text) for text in texts]),
        "pages": {"count": len(per_page), "chunks_per_page": _summary(list(per_page.values()))},
        "empty_chunks": sum(1 for text in texts if not text.strip()),
        "placeholder_chunks": sum(1 for text in texts if text.strip() == IMAGE_PLACEHOLDER),
        **settings,
    }


async def collect_chunk_stats(
    client: Any, *, document_id: str, ingest_path: str, index_name: str | None = None
) -> dict[str, Any]:
    """``compute_chunk_stats`` over one document's chunks as stored in the index.

    Refreshes the index first so chunks written moments ago are searchable;
    ``client`` needs that privilege (the platform writer client has it). Past
    ``STATS_MAX_CHUNKS`` the stats cover the first chunks read and
    ``truncated`` is set; ``indexed_chunk_count`` is the full count.
    """
    index_name = index_name or get_index_name()
    await client.indices.refresh(index=index_name)
    response = await client.search(
        index=index_name,
        body={
            "size": STATS_MAX_CHUNKS,
            "track_total_hits": True,
            "query": document_chunks_query(document_id),
            "_source": {"includes": ["text", "page", *SETTING_FIELDS]},
        },
    )
    hits = response.get("hits", {})
    chunks = [hit.get("_source") or {} for hit in hits.get("hits", [])]
    total = hits.get("total")
    indexed = total.get("value", len(chunks)) if isinstance(total, dict) else len(chunks)
    return {
        **compute_chunk_stats(chunks, ingest_path=ingest_path),
        "indexed_chunk_count": indexed,
        "truncated": indexed > len(chunks),
    }


def _flattened(prefix: str, value: Any) -> dict[str, Any]:
    """Nested stats as dotted keys; lists as text (trace metadata is flat)."""
    if isinstance(value, dict):
        flat: dict[str, Any] = {}
        for key, inner in value.items():
            flat.update(_flattened(f"{prefix}.{key}", inner))
        return flat
    if isinstance(value, list):
        return {prefix: ", ".join(str(item) for item in value)}
    return {prefix: value}


async def record_chunk_stats(file_task: FileTask, *, client: Any = None) -> None:
    """Add ``chunk_stats`` to a just-ingested file's task result, and trace them.

    Only files that were (re)indexed: their result names the ``ingest_path``
    that chunked them; unchanged, skipped and removed files have none. Never
    fails the file: on any error the stats are logged and left out. ``client``
    defaults to the platform writer client, which can refresh the index.
    """
    result = file_task.result
    if file_task.status != TaskStatus.COMPLETED or not isinstance(result, dict):
        return
    ingest_path = result.get("ingest_path")
    document_id = file_task.document_id or result.get("id")
    if not ingest_path or not document_id:
        return
    client = client or clients.opensearch
    if client is None:
        return

    # Its own trace: Langflow-path files have no backend ingest trace to join;
    # the task's session groups it with the file's other traces.
    with trace_root(
        "ingest.chunk_stats",
        attributes={"document_id": document_id, "ingest_path": ingest_path},
    ) as trace:
        try:
            stats = await asyncio.wait_for(
                collect_chunk_stats(client, document_id=document_id, ingest_path=ingest_path),
                timeout=STATS_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "Chunk stats unavailable; file result left without them",
                document_id=document_id,
                ingest_path=ingest_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            trace.fail(type(exc).__name__)
            return
        trace.set(**_flattened("chunk_stats", stats))
    file_task.result = {**result, "chunk_stats": stats}
