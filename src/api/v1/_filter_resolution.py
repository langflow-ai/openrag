"""Shared helper to resolve a `filter_id` into concrete filter values for v1 endpoints.

API consumers expect `filter_id` on /v1/chat, /v1/search, /v1/documents to "just work"
without first GETting the filter, parsing its `query_data`, and resending the parts as
inline `filters`. This helper performs that lookup + normalization server-side.

Wildcard handling mirrors `frontend/lib/filter-normalization.ts::buildSearchPayloadFilters`:
a dimension like `data_sources: ["*"]` collapses to `[]` (i.e. "no filter on this field").
"""

import json
from typing import Any

from fastapi import HTTPException

_FILTER_DIMENSIONS = ("data_sources", "document_types", "owners", "connector_types")


def _strip_wildcards(filters: dict[str, Any] | None) -> dict[str, list[str]]:
    """Drop `["*"]` and empty lists from each filter dimension."""
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
