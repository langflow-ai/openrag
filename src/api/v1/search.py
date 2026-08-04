"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""

from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.v1._filter_resolution import merge_filter_overrides, resolve_filter_id
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
    # OpenSearch fuzziness for the keyword-match clause. See the
    # openrag_search MCP tool description for accepted values.
    # Defaults to "AUTO:7,10".
    fuzziness: str | None = None


class RawSearchV1Body(BaseModel):
    query: dict[str, Any] | str
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

    # API-key requests can arrive without a JWT. Set the auth context before
    # resolving filters so search_tool() can still identify the caller.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
        )
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

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
            fuzziness=body.fuzziness,
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


async def raw_search_endpoint(
    body: RawSearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(require_api_key_permission("search:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Execute a raw OpenSearch DSL query against the knowledge base. POST /v1/search/raw

    Unlike /v1/search's hybrid semantic+keyword search, `query` is passed
    through as OpenSearch Query DSL (bool queries, aggregations, sort, etc.).
    Still runs through the caller's ACL-scoped OpenSearch client and strips
    embedding vectors from results.
    """
    query = body.query
    if isinstance(query, str) and not query.strip():
        return JSONResponse({"error": "Query is required"}, status_code=400)
    if not isinstance(query, (dict, str)):
        return JSONResponse(
            {"error": "query must be an OpenSearch DSL object or a string"}, status_code=400
        )

    # API-key requests can arrive without a JWT. Set the auth context before
    # resolving filters so raw_search() can still identify the caller.
    set_auth_context(user.user_id, user.jwt_token)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
        )
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

    logger.debug(
        "Public API raw search request",
        user_id=user.user_id,
        filters=resolved_filters,
        limit=resolved_limit,
        score_threshold=resolved_score_threshold,
        filter_id=body.filter_id,
    )

    try:
        result = await search_service.raw_search(
            query,
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            filters=resolved_filters or {},
            limit=resolved_limit,
            score_threshold=resolved_score_threshold,
        )
        return JSONResponse(result)

    except OpenSearchDiskSpaceError as e:
        logger.error(
            "Raw search blocked by disk space constraint", error=str(e), user_id=user.user_id
        )
        return JSONResponse({"error": DISK_SPACE_ERROR_MESSAGE}, status_code=507)
    except Exception as e:
        error_msg = str(e)
        logger.error("Raw search failed", error=error_msg, user_id=user.user_id)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=400)
