from collections.abc import Iterable

from opensearchpy.exceptions import NotFoundError

from services.search_cache import invalidate_corpus_caches
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def collect_visible_document_ids(
    opensearch_client,
    *,
    index: str,
    query: dict,
    source: bool | list[str] = False,
    page_size: int = 1000,
    scroll_ttl: str = "2m",
) -> list[str]:
    """Collect visible document IDs for a query using the caller's OpenSearch client."""
    search_body = {"query": query, "size": page_size, "_source": source}
    response = await opensearch_client.search(
        index=index,
        body=search_body,
        scroll=scroll_ttl,
    )
    scroll_id = response.get("_scroll_id")
    document_ids: list[str] = []

    try:
        while True:
            hits = response.get("hits", {}).get("hits", [])
            document_ids.extend(hit["_id"] for hit in hits if hit.get("_id"))
            if not hits or len(hits) < page_size or not scroll_id:
                break
            response = await opensearch_client.scroll(scroll_id=scroll_id, scroll=scroll_ttl)
            scroll_id = response.get("_scroll_id") or scroll_id
    finally:
        if scroll_id and hasattr(opensearch_client, "clear_scroll"):
            try:
                await opensearch_client.clear_scroll(scroll_id=scroll_id)
            except Exception as e:
                logger.debug("Failed to clear OpenSearch scroll context", error=str(e))

    return document_ids


async def delete_document_ids(
    opensearch_client,
    *,
    index: str,
    document_ids: Iterable[str],
    refresh: bool = True,
) -> int:
    """Delete concrete OpenSearch document IDs through the caller's client.

    delete_by_query is silently no-opped under DLS / certain security plugins
    (returns deleted:N but leaves the docs in place). Single deletes keyed on
    the primary _id are reliable, so enumerate visible IDs first and then issue
    a delete per ID.
    """
    deleted_count = 0
    try:
        for document_id in document_ids:
            try:
                result = await opensearch_client.delete(
                    index=index,
                    id=document_id,
                    refresh=refresh,
                )
            except NotFoundError:
                continue

            if result.get("result") == "deleted":
                deleted_count += 1
    finally:
        if deleted_count:
            invalidate_corpus_caches()

    return deleted_count


class BulkDeleteError(RuntimeError):
    """A bulk delete failed part-way; ``deleted_count`` holds confirmed deletions.

    Only deletions acknowledged by a successful ``_bulk`` response are counted.
    If a request itself failed, any deletions it may have applied are unknown
    and are not included.
    """

    def __init__(self, message: str, deleted_count: int = 0):
        super().__init__(message)
        self.deleted_count = deleted_count


async def bulk_delete_document_ids(
    opensearch_client,
    *,
    index: str,
    document_ids: Iterable[str],
    refresh: bool = True,
    batch_size: int = 500,
) -> int:
    """Delete concrete OpenSearch document IDs using batched ``_bulk`` requests.

    Same ID-keyed delete semantics as :func:`delete_document_ids` (so it stays
    DLS-safe), but one request per ``batch_size`` IDs instead of one per ID, and
    a single index refresh on the final batch instead of one per delete. Intended
    for user-facing deletes of many chunks, where per-ID round trips and
    per-delete refreshes dominate latency.

    Missing documents (404) are ignored. Any other per-item failure is raised as
    a :class:`BulkDeleteError` after all batches have been attempted. A failed
    request stops further batches and is also raised as a ``BulkDeleteError``
    (chained to the original exception). Either way, ``deleted_count`` on the
    error carries the deletions confirmed so far.
    """
    ids = list(document_ids)
    deleted_count = 0
    first_error: str | None = None
    try:
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            is_last = start + batch_size >= len(ids)
            try:
                response = await opensearch_client.bulk(
                    body=[{"delete": {"_index": index, "_id": doc_id}} for doc_id in batch],
                    refresh=refresh and is_last,
                )
            except Exception as e:
                raise BulkDeleteError(str(e), deleted_count) from e
            for item in response.get("items", []):
                action = item.get("delete", {})
                if action.get("result") == "deleted":
                    deleted_count += 1
                elif action.get("status") != 404 and first_error is None:
                    first_error = str(action.get("error") or action.get("status"))
    finally:
        if deleted_count:
            invalidate_corpus_caches()

    if first_error is not None:
        raise BulkDeleteError(f"Bulk delete failed for some chunks: {first_error}", deleted_count)
    return deleted_count
