"""Filter membership ("filters as collections") for ingested documents.

A document joins a saved knowledge filter when its chunks carry the label
``collection:<filter id>`` in the ``labels`` keyword field, and the filter's
``query_data`` holds a matching ``labels`` condition. The existing ``filter_id``
handling on search and chat then scopes results to the filter's members.

Labels are written when an ingest task completes rather than during chunking,
so the Langflow and non-Langflow ingestion paths both get them without flow
edits, and membership is in place before the task reports COMPLETED.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from models.tasks import TaskStatus
from utils.logging_config import get_logger

if TYPE_CHECKING:
    from models.tasks import FileTask, UploadTask

logger = get_logger(__name__)

COLLECTION_LABEL_PREFIX = "collection:"
LABELS_FIELD = "labels"
KNOWLEDGE_FILTERS_INDEX = "knowledge_filters"
FILTER_EDIT_PERMISSION = "kf:edit:own"

_ANONYMOUS_USER_IDS = (None, "", "anonymous")

# Appends each label the chunk does not already carry. Idempotent, so a retried
# task can run it again safely.
_ADD_LABELS_SCRIPT = """
if (ctx._source.labels == null) {
    ctx._source.labels = new ArrayList();
} else if (!(ctx._source.labels instanceof List)) {
    def existing = ctx._source.labels;
    ctx._source.labels = new ArrayList();
    ctx._source.labels.add(existing);
}
boolean changed = false;
for (def label : params.labels) {
    if (!ctx._source.labels.contains(label)) {
        ctx._source.labels.add(label);
        changed = true;
    }
}
if (!changed) {
    ctx.op = 'noop';
}
"""


def collection_label(filter_id: str) -> str:
    """The label that marks a chunk as a member of ``filter_id``."""
    return f"{COLLECTION_LABEL_PREFIX}{filter_id}"


def normalize_filter_ids(raw: Iterable[Any] | None) -> list[str]:
    """Drop blanks and duplicates from a ``filter_ids`` form value, keeping order."""
    if not raw or isinstance(raw, str | bytes):
        # A bare string means a direct call that bypassed form parsing.
        raw = [raw] if isinstance(raw, str) else []
    seen: dict[str, None] = {}
    for value in raw:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value:
            seen.setdefault(value, None)
    return list(seen)


async def validate_ingest_filter_ids(
    filter_ids: list[str],
    *,
    request,
    user,
    rbac,
    knowledge_filter_service,
) -> JSONResponse | None:
    """Reject the ingest request if any filter is unknown or not editable.

    The rules match ``PUT /knowledge-filter/{id}``: the caller must be able to
    see the filter (the DLS-scoped lookup finds it) and hold ``kf:edit:own``.
    Returns an error response, or None when every filter is acceptable.
    """
    if not filter_ids:
        return None

    from auth.permission_dependencies import has_effective_permission

    if not await has_effective_permission(request, user, rbac, FILTER_EDIT_PERMISSION):
        return JSONResponse(
            {
                "error": "Insufficient permissions to add documents to a knowledge filter",
                "required_permission": FILTER_EDIT_PERMISSION,
            },
            status_code=403,
        )

    for filter_id in filter_ids:
        result = await knowledge_filter_service.get_knowledge_filter(
            filter_id, user_id=user.user_id, jwt_token=user.jwt_token
        )
        if not result.get("success"):
            return JSONResponse(
                {"error": f"Knowledge filter {filter_id} not found", "filter_id": filter_id},
                status_code=404,
            )
    return None


def build_own_document_chunks_query(document_id: str, user_id: str | None) -> dict:
    """Chunks of ``document_id`` that belong to ``user_id``.

    For the anonymous (no-auth) user, chunks indexed without an owner count as
    theirs too.
    """
    from utils.opensearch_queries import build_owner_or_shared_filter

    owner_clause: dict
    if user_id in _ANONYMOUS_USER_IDS:
        owner_clause = build_owner_or_shared_filter("anonymous")
    else:
        owner_clause = {"term": {"owner": user_id}}
    return {
        "bool": {
            "filter": [
                {"term": {"document_id": document_id}},
                owner_clause,
            ]
        }
    }


def _labelable(file_task: FileTask) -> bool:
    if not file_task.filter_ids or file_task.collection_labels_applied:
        return False
    if not file_task.document_id:
        return False
    # SKIPPED with a document_id means identical content is already indexed:
    # it still belongs in the requested filters.
    return file_task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)


async def _load_filter(os_client, filter_id: str) -> dict | None:
    try:
        result = await os_client.get(index=KNOWLEDGE_FILTERS_INDEX, id=filter_id)
    except Exception as e:
        if "not_found" in str(e) or "NotFoundError" in type(e).__name__:
            return None
        raise
    if not result.get("found"):
        return None
    return result.get("_source") or {}


def _query_data(filter_doc: dict) -> dict:
    raw = filter_doc.get("query_data") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _ensure_filter_condition(os_client, filter_id: str, filter_doc: dict) -> None:
    """Add ``labels: [collection:<id>]`` to the filter if it isn't there yet."""
    label = collection_label(filter_id)
    query_data = _query_data(filter_doc)
    filters = query_data.get("filters")
    if not isinstance(filters, dict):
        filters = {}
    labels = filters.get(LABELS_FIELD)
    if not isinstance(labels, list):
        labels = []
    if label in labels:
        return
    filters[LABELS_FIELD] = [*labels, label]
    query_data["filters"] = filters
    await os_client.update(
        index=KNOWLEDGE_FILTERS_INDEX,
        id=filter_id,
        body={
            "doc": {
                "query_data": json.dumps(query_data),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        },
        refresh="wait_for",
    )
    logger.info("Added collection condition to knowledge filter", filter_id=filter_id)


async def apply_collection_labels(upload_task: UploadTask, user_id: str | None) -> None:
    """Stamp filter membership on every successfully ingested file in the task.

    Runs after the index refresh and before the task is marked COMPLETED, so a
    caller polling for COMPLETED sees membership already in place. Uses the
    admin client: the caller's JWT may have expired by the time a long task
    finishes, and access was checked when the request came in.

    A filter deleted since the request was accepted is skipped with a warning.
    A failed label write is logged and recorded as a warning on the file's
    result; the file stays COMPLETED because its chunks were indexed.
    """
    pending = [ft for ft in upload_task.file_tasks.values() if _labelable(ft)]
    if not pending:
        return

    from config.settings import clients, get_index_name

    os_client = clients.opensearch
    if os_client is None:
        logger.error("Cannot apply collection labels: OpenSearch client unavailable")
        return

    filter_docs: dict[str, dict | None] = {}
    for filter_id in {fid for ft in pending for fid in ft.filter_ids}:
        try:
            filter_docs[filter_id] = await _load_filter(os_client, filter_id)
        except Exception as e:
            logger.error(
                "Failed to load knowledge filter for collection labels",
                filter_id=filter_id,
                error=str(e),
            )
            filter_docs[filter_id] = None
            continue
        if filter_docs[filter_id] is None:
            logger.warning(
                "Knowledge filter no longer exists; skipping collection label",
                filter_id=filter_id,
                task_id=upload_task.task_id,
            )

    labeled_filters: set[str] = set()
    index_name = get_index_name()
    for file_task in pending:
        live_ids = [fid for fid in file_task.filter_ids if filter_docs.get(fid) is not None]
        if not live_ids:
            file_task.collection_labels_applied = True
            continue
        labels = [collection_label(fid) for fid in live_ids]
        try:
            await os_client.update_by_query(
                index=index_name,
                body={
                    "query": build_own_document_chunks_query(file_task.document_id, user_id),
                    "script": {
                        "lang": "painless",
                        "source": _ADD_LABELS_SCRIPT,
                        "params": {"labels": labels},
                    },
                },
                refresh=True,
                conflicts="proceed",
            )
        except Exception as e:
            logger.error(
                "Failed to apply collection labels",
                task_id=upload_task.task_id,
                document_id=file_task.document_id,
                filter_ids=live_ids,
                error=str(e),
            )
            result = file_task.result if isinstance(file_task.result, dict) else {}
            result["collection_warning"] = "The document could not be added to its filters."
            file_task.result = result
            continue
        file_task.collection_labels_applied = True
        labeled_filters.update(live_ids)

    for filter_id in labeled_filters:
        try:
            await _ensure_filter_condition(os_client, filter_id, filter_docs[filter_id] or {})
        except Exception as e:
            logger.error(
                "Failed to add collection condition to knowledge filter",
                filter_id=filter_id,
                error=str(e),
            )

    if labeled_filters:
        try:
            from services.search_cache import invalidate_corpus_caches

            invalidate_corpus_caches()
        except Exception:
            pass
