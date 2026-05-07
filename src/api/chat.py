from typing import Optional, Any, Dict

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger

from dependencies import (
    get_chat_service,
    get_session_manager,
    get_current_user,
    require_permission,
)
from session_manager import User

logger = get_logger(__name__)


def _openrag_user_id(user: User) -> str:
    return getattr(user, "db_user_id", None) or user.user_id


async def _assert_owns(session_id: Optional[str], user_id: str) -> None:
    """Raise 403 if `session_id` is set but not owned by `user_id`.

    No-op when `session_id` is None (new conversation, nothing to check).
    Raise 404 if a session is referenced that doesn't exist — don't leak
    existence to non-owners.
    """
    if not session_id:
        return
    from services.session_ownership_service import session_ownership_service
    owner = await session_ownership_service.get_session_owner(session_id)
    if owner is None:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    if owner != user_id:
        raise HTTPException(status_code=403, detail={"error": "session_forbidden"})


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
    user: User = Depends(require_permission("chat:use")),
):
    """Handle chat requests"""
    if not body.prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    storage_user_id = _openrag_user_id(user)
    await _assert_owns(body.previous_response_id, storage_user_id)

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
                storage_user_id=storage_user_id,
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
            storage_user_id=storage_user_id,
        )
        return JSONResponse(result)


async def langflow_endpoint(
    body: ChatBody,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("chat:use")),
):
    """Handle Langflow chat requests"""
    if not body.prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    storage_user_id = _openrag_user_id(user)
    await _assert_owns(body.previous_response_id, storage_user_id)

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
                    owner=user.user_id,
                    owner_name=user.name,
                    owner_email=user.email,
                    storage_user_id=storage_user_id,
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
                owner=user.user_id,
                owner_name=user.name,
                owner_email=user.email,
                storage_user_id=storage_user_id,
            )
            return JSONResponse(result)

    except Exception as e:
        logger.exception("[CHAT] Langflow request failed")
        return JSONResponse(
            {"error": f"Langflow request failed: {str(e)}"}, status_code=500
        )


async def chat_history_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(require_permission("conversations:read:own")),
):
    """Get chat history for a user"""
    try:
        history = await chat_service.get_chat_history(_openrag_user_id(user))
        return JSONResponse(history)
    except Exception as e:
        logger.exception("[CHAT] Failed to get chat history")
        return JSONResponse(
            {"error": f"Failed to get chat history: {str(e)}"}, status_code=500
        )


async def langflow_history_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(require_permission("conversations:read:own")),
):
    """Get langflow chat history for a user"""
    try:
        history = await chat_service.get_langflow_history(_openrag_user_id(user))
        return JSONResponse(history)
    except Exception as e:
        logger.exception("[CHAT] Failed to get langflow history")
        return JSONResponse(
            {"error": f"Failed to get langflow history: {str(e)}"}, status_code=500
        )


async def delete_session_endpoint(
    session_id: str,
    chat_service=Depends(get_chat_service),
    user: User = Depends(require_permission("conversations:delete:own")),
):
    """Delete a chat session"""
    storage_user_id = _openrag_user_id(user)
    await _assert_owns(session_id, storage_user_id)
    try:
        result = await chat_service.delete_session(storage_user_id, session_id)

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
