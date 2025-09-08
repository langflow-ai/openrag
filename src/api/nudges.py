from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def nudges_from_kb_endpoint(request: Request, chat_service, session_manager):
    """Get nudges for a user"""
    user = request.state.user
    user_id = user.user_id
    jwt_token = request.state.jwt_token

    try:
        result = await chat_service.langflow_nudges_chat(
            user_id,
            jwt_token,
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
    jwt_token = request.state.jwt_token

    try:
        result = await chat_service.langflow_nudges_chat(
            user_id,
            jwt_token,
            previous_response_id=chat_id,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get nudges: {str(e)}"}, status_code=500
        )
