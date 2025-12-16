"""
Public API v1 Search endpoint.

Provides semantic search functionality.
Uses API key authentication.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def search_endpoint(request: Request, search_service, session_manager):
    """
    Perform semantic search on documents.

    POST /api/v1/search

    Request body:
        {
            "query": "What is RAG?",
            "filters": {  // optional
                "data_sources": ["doc.pdf"],
                "document_types": ["application/pdf"]
            },
            "limit": 10,  // optional, default 10
            "score_threshold": 0.5  // optional, default 0
        }

    Response:
        {
            "results": [
                {
                    "filename": "doc.pdf",
                    "text": "RAG stands for...",
                    "score": 0.85,
                    "page": 1,
                    "mimetype": "application/pdf"
                }
            ]
        }
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    query = data.get("query", "").strip()
    if not query:
        return JSONResponse(
            {"error": "Query is required"},
            status_code=400,
        )

    filters = data.get("filters", {})
    limit = data.get("limit", 10)
    score_threshold = data.get("score_threshold", 0)

    user = request.state.user
    user_id = user.user_id

    # Note: API key auth doesn't have JWT
    jwt_token = None

    logger.debug(
        "Public API search request",
        user_id=user_id,
        query=query,
        filters=filters,
        limit=limit,
        score_threshold=score_threshold,
    )

    try:
        result = await search_service.search(
            query,
            user_id=user_id,
            jwt_token=jwt_token,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )

        # Transform results to public API format
        results = []
        for item in result.get("results", []):
            results.append({
                "filename": item.get("filename"),
                "text": item.get("text"),
                "score": item.get("score"),
                "page": item.get("page"),
                "mimetype": item.get("mimetype"),
            })

        return JSONResponse({"results": results})

    except Exception as e:
        error_msg = str(e)
        logger.error("Search failed", error=error_msg, user_id=user_id)

        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
