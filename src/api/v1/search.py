"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""

from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.v1._filter_resolution import resolve_filter_id
from auth_context import set_auth_context
from dependencies import (
    get_knowledge_filter_service,
    get_search_service,
    require_api_key_permission,
)
from session_manager import User
from utils.logging_config import get_logger
from utils.opensearch_utils import DISK_SPACE_ERROR_MESSAGE, OpenSearchDiskSpaceError

logger = get_logger(__name__)


class SearchV1Body(BaseModel):
    query: str
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: str | None = None


async def search_endpoint(
    body: SearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(require_api_key_permission("search:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Perform semantic search on documents. POST /v1/search"""
    query = body.query.strip()
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)

    # API-key auth has no JWT; the gate inside search_service.search()
    # skips set_auth_context() in that case, leaving search_tool() unable to
    # resolve the user. Set it explicitly here, mirroring v1 chat.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=None,
        )
        if not body.filters:
            resolved_filters = resolved["filters"]
        if body.limit == 10:
            resolved_limit = resolved["limit"]
        if body.score_threshold == 0:
            resolved_score_threshold = resolved["score_threshold"]

    logger.debug(
        "Public API search request",
        user_id=user.user_id,
        query=query,
        filters=resolved_filters,
        limit=resolved_limit,
        score_threshold=resolved_score_threshold,
        filter_id=body.filter_id,
    )

    try:
        result = await search_service.search(
            query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=resolved_filters or {},
            limit=resolved_limit,
            score_threshold=resolved_score_threshold,
        )

        results = [
            {
                "filename": item.get("filename"),
                "text": item.get("text"),
                "score": item.get("score"),
                "page": item.get("page"),
                "mimetype": item.get("mimetype"),
            }
            for item in result.get("results", [])
        ]

        return JSONResponse({"results": results})

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
