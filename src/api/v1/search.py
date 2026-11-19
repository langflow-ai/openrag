"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""

import asyncio
from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.files import validate_date_filter_bounds
from api.v1._filter_resolution import merge_filter_overrides, resolve_filter_id
from auth_context import set_auth_context
from dependencies import (
    get_knowledge_filter_service,
    get_search_service,
    require_api_key_permission,
)
from observability.tracing import trace_context
from services.dataset_search_service import DatasetSearchService, resolve_datasets, rrf_merge
from session_manager import User
from utils.dataset_selection import resolve_v1_selection
from utils.logging_config import get_logger
from utils.opensearch_utils import DISK_SPACE_ERROR_MESSAGE, OpenSearchDiskSpaceError

logger = get_logger(__name__)


class SearchV1Body(BaseModel):
    query: str
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: str | None = None
    # Imported datasets to search alongside documents: omit (or "*") for every
    # dataset you can see, a list of dataset ids for just those, [] for none.
    datasets: list[str] | str | None = None


async def search_endpoint(
    body: SearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(require_api_key_permission("search:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Perform semantic search on documents and imported datasets. POST /v1/search"""
    query = body.query.strip()
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)

    # API-key requests can arrive without a JWT. Set the auth context before
    # resolving filters so search_tool() can still identify the caller.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    saved_filters: dict[str, Any] | None = None
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
        )
        saved_filters = resolved["filters"]
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

    validate_date_filter_bounds(resolved_filters)

    try:
        selection = resolve_v1_selection(
            body_has_datasets="datasets" in body.model_fields_set,
            body_datasets=body.datasets,
            inline_filters=body.filters,
            saved_filters=saved_filters,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    logger.debug(
        "Public API search request",
        user_id=user.user_id,
        query=query,
        filters=resolved_filters,
        limit=resolved_limit,
        score_threshold=resolved_score_threshold,
        filter_id=body.filter_id,
        datasets=selection,
    )

    try:
        dataset_errors: list[dict[str, Any]] = []
        datasets: list[Any] = []
        try:
            # Empty unless the feature is available and the user can see a
            # selected dataset; then this endpoint behaves exactly as before.
            datasets = await resolve_datasets(selection)
        except Exception as e:
            logger.error("Dataset lookup failed", error=str(e), user_id=user.user_id)
            dataset_errors.append({"dataset_id": None, "code": "lookup_failed"})

        async def search_documents() -> dict[str, Any]:
            # The search trace records which saved filter was applied.
            with trace_context(
                attributes={"openrag.search.filter_id": body.filter_id} if body.filter_id else None
            ):
                return await search_service.search(
                    query,
                    user_id=user.user_id,
                    jwt_token=user.jwt_token,
                    filters=resolved_filters or {},
                    limit=resolved_limit,
                    score_threshold=resolved_score_threshold,
                )

        dataset_hits: list[dict[str, Any]] = []
        if datasets:
            dataset_task = asyncio.ensure_future(
                DatasetSearchService(search_service.session_manager).search(
                    query,
                    user_id=user.user_id,
                    jwt_token=user.jwt_token,
                    dataset_ids=[record.id for record in datasets],
                    limit=resolved_limit,
                )
            )
            try:
                result = await search_documents()
            except BaseException:
                dataset_task.cancel()
                raise
            dataset_result = await dataset_task
            dataset_hits = dataset_result["results"]
            dataset_errors.extend(dataset_result["errors"])
        else:
            result = await search_documents()

        found = result.get("results", [])
        if dataset_hits:
            found = rrf_merge([found, dataset_hits], limit=resolved_limit)

        results = [
            {
                "filename": item.get("filename"),
                "text": item.get("text"),
                "score": item.get("score"),
                "page": item.get("page"),
                "mimetype": item.get("mimetype"),
                "dataset": item.get("dataset"),
            }
            for item in found
        ]

        payload: dict[str, Any] = {"results": results}
        if dataset_errors:
            payload["dataset_errors"] = dataset_errors
        return JSONResponse(payload)

    except OpenSearchDiskSpaceError as e:
        logger.error("Search blocked by disk space constraint", error=str(e), user_id=user.user_id)
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        error_msg = str(e)
        logger.error("Search failed", error=error_msg, user_id=user.user_id)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
