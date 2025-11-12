from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def nudges_from_kb_endpoint(request: Request, chat_service, session_manager):
    """Get nudges for a user"""
    user = request.state.user
    user_id = user.user_id
    jwt_token = session_manager.get_effective_jwt_token(user_id, request.state.jwt_token)

    try:
        # Parse request body for filters
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        filters = body.get("filters")
        limit = body.get("limit")
        score_threshold = body.get("score_threshold")

        result = await chat_service.langflow_nudges_chat(
            user_id,
            jwt_token,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get nudges: {str(e)}"}, status_code=500
        )


async def nudges_from_chat_id_endpoint(request: Request, chat_service, session_manager):
    """Get nudges for a user"""
    user = request.state.user
    user_id = user.user_id
    chat_id = request.path_params["chat_id"]

    jwt_token = session_manager.get_effective_jwt_token(user_id, request.state.jwt_token)

    try:
        # Parse request body for filters
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        filters = body.get("filters")
        limit = body.get("limit")
        score_threshold = body.get("score_threshold")

        result = await chat_service.langflow_nudges_chat(
            user_id,
            jwt_token,
            previous_response_id=chat_id,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get nudges: {str(e)}"}, status_code=500
        )
