from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def search(request: Request, search_service, session_manager):
    """Search for documents"""
    try:
        payload = await request.json()
        query = payload.get("query")
        if not query:
            return JSONResponse({"error": "Query is required"}, status_code=400)

        filters = payload.get("filters", {})  # Optional filters, defaults to empty dict
        limit = payload.get("limit", 10)  # Optional limit, defaults to 10
        score_threshold = payload.get(
            "scoreThreshold", 0
        )  # Optional score threshold, defaults to 0

        user = request.state.user
        jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

        logger.debug(
            "Search API request",
            user=str(user),
            user_id=user.user_id if user else None,
            has_jwt_token=jwt_token is not None,
            query=query,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )

        result = await search_service.search(
            query,
            user_id=user.user_id,
            jwt_token=jwt_token,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
        return JSONResponse(result, status_code=200)
    except Exception as e:
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
