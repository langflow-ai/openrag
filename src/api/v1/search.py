"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""
from typing import Any, Dict, Optional

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger
from dependencies import get_search_service, get_api_key_user_async
from session_manager import User

logger = get_logger(__name__)


class SearchV1Body(BaseModel):
    query: str
    filters: Optional[Dict[str, Any]] = None
    limit: int = 10
    score_threshold: float = 0


async def search_endpoint(
    body: SearchV1Body,
    search_service=Depends(get_search_service),
    user: User = Depends(get_api_key_user_async),
):
    """Perform semantic search on documents. POST /v1/search"""
    query = body.query.strip()
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)

    logger.debug(
        "Public API search request",
        user_id=user.user_id,
        query=query,
        filters=body.filters,
        limit=body.limit,
        score_threshold=body.score_threshold,
    )

    try:
        result = await search_service.search(
            query,
            user_id=user.user_id,
            jwt_token=None,  # API key auth has no JWT
            filters=body.filters or {},
            limit=body.limit,
            score_threshold=body.score_threshold,
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

    except Exception as e:
        error_msg = str(e)
        logger.error("Search failed", error=error_msg, user_id=user.user_id)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
