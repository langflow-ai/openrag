"""Shared helper to resolve a `filter_id` into concrete filter values for v1 endpoints.

API consumers expect `filter_id` on /v1/chat, /v1/search, /v1/documents to "just work"
without first GETting the filter, parsing its `query_data`, and resending the parts as
inline `filters`. This helper performs that lookup + normalization server-side.

Wildcard handling mirrors `frontend/lib/filter-normalization.ts::buildSearchPayloadFilters`.
Each filter dimension is a list; if that list contains the wildcard value `"*"`
(for example, `data_sources: ["*"]`), the dimension is treated as unscoped.
"""

import json
from typing import Any

from fastapi import HTTPException

_FILTER_DIMENSIONS = ("data_sources", "document_types", "owners", "connector_types")


def _strip_wildcards(filters: dict[str, Any] | None) -> dict[str, list[str]]:
    """Keep only filter dimensions that contain concrete values."""
    if not filters:
        return {}
    cleaned: dict[str, list[str]] = {}
    for key in _FILTER_DIMENSIONS:
        values = filters.get(key)
        if not values or not isinstance(values, list):
            continue
        if "*" in values:
            continue
        cleaned[key] = values
    return cleaned


async def resolve_filter_id(
    filter_id: str,
    knowledge_filter_service,
    user_id: str,
    jwt_token: str | None,
) -> dict[str, Any]:
    """Resolve `filter_id` -> `{"filters": {...}, "limit": int, "score_threshold": float}`.

    Raises HTTPException(404) if the filter does not exist or is not accessible to
    the calling user.
    """
    result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user_id, jwt_token=jwt_token
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail={"error": f"Filter {filter_id} not found"},
        )

    filter_doc = result["filter"]
    query_data_raw = filter_doc.get("query_data") or "{}"
    if isinstance(query_data_raw, str):
        try:
            query_data = json.loads(query_data_raw)
        except json.JSONDecodeError:
            query_data = {}
    else:
        query_data = query_data_raw or {}

    return {
        "filters": _strip_wildcards(query_data.get("filters")),
        "limit": query_data.get("limit", 10),
        "score_threshold": query_data.get("scoreThreshold", 0),
    }


def merge_filter_overrides(
    resolved: dict[str, Any],
    request_body: Any,
) -> tuple[dict[str, Any] | None, int, float]:
    """Merge resolved filter values with explicitly provided request fields.

    Inline request fields override saved filter values by field presence, not by
    truthiness. This lets callers intentionally set values such as `limit=10`,
    `score_threshold=0`, or `filters={}`.
    """
    provided_fields: set[str] = getattr(request_body, "model_fields_set", set())

    filters: dict[str, Any] | None = resolved["filters"]
    if "filters" in provided_fields:
        inline_filters = request_body.filters
        if inline_filters:
            filters = {**resolved["filters"], **inline_filters}
        else:
            filters = inline_filters

    limit = request_body.limit
    if "limit" not in provided_fields:
        limit = resolved["limit"]

    score_threshold = request_body.score_threshold
    if "score_threshold" not in provided_fields:
        score_threshold = resolved["score_threshold"]

    return filters, limit, score_threshold
