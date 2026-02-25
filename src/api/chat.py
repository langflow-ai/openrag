from typing import Optional, Any, Dict

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger

from dependencies import get_chat_service, get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


class ChatBody(BaseModel):
    prompt: str
    previous_response_id: Optional[str] = None
    stream: bool = False
    filters: Optional[Dict[str, Any]] = None
    limit: int = 10
    scoreThreshold: float = 0
    filter_id: Optional[str] = None


async def chat_endpoint(
    body: ChatBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Handle chat requests"""
    if not body.prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    jwt_token = user.jwt_token

    if body.filters:
        from auth_context import set_search_filters
        set_search_filters(body.filters)

    from auth_context import set_search_limit, set_score_threshold
    set_search_limit(body.limit)
    set_score_threshold(body.scoreThreshold)

    if body.stream:
        return StreamingResponse(
            await chat_service.chat(
                body.prompt,
                user.user_id,
                jwt_token,
                previous_response_id=body.previous_response_id,
                stream=True,
                filter_id=body.filter_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )
    else:
        result = await chat_service.chat(
            body.prompt,
            user.user_id,
            jwt_token,
            previous_response_id=body.previous_response_id,
            stream=False,
            filter_id=body.filter_id,
        )
        return JSONResponse(result)


async def langflow_endpoint(
    body: ChatBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Handle Langflow chat requests"""
    if not body.prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    jwt_token = user.jwt_token

    if body.filters:
        from auth_context import set_search_filters
        set_search_filters(body.filters)

    from auth_context import set_search_limit, set_score_threshold
    set_search_limit(body.limit)
    set_score_threshold(body.scoreThreshold)

    try:
        if body.stream:
            return StreamingResponse(
                await chat_service.langflow_chat(
                    body.prompt,
                    user.user_id,
                    jwt_token,
                    previous_response_id=body.previous_response_id,
                    stream=True,
                    filter_id=body.filter_id,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control",
                },
            )
        else:
            result = await chat_service.langflow_chat(
                body.prompt,
                user.user_id,
                jwt_token,
                previous_response_id=body.previous_response_id,
                stream=False,
                filter_id=body.filter_id,
            )
            return JSONResponse(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error("Langflow request failed", error=str(e))
        return JSONResponse(
            {"error": f"Langflow request failed: {str(e)}"}, status_code=500
        )


async def chat_history_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_current_user),
):
    """Get chat history for a user"""
    try:
        history = await chat_service.get_chat_history(user.user_id)
        return JSONResponse(history)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get chat history: {str(e)}"}, status_code=500
        )


async def langflow_history_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_current_user),
):
    """Get langflow chat history for a user"""
    try:
        history = await chat_service.get_langflow_history(user.user_id)
        return JSONResponse(history)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get langflow history: {str(e)}"}, status_code=500
        )


async def delete_session_endpoint(
    session_id: str,
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_current_user),
):
    """Delete a chat session"""
    try:
        result = await chat_service.delete_session(user.user_id, session_id)

        if result.get("success"):
            return JSONResponse({"message": "Session deleted successfully"})
        else:
            return JSONResponse(
                {"error": result.get("error", "Failed to delete session")},
                status_code=500
            )
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return JSONResponse(
            {"error": f"Failed to delete session: {str(e)}"}, status_code=500
        )
