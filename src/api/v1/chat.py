"""
Public API v1 Chat endpoint.

Provides chat functionality with streaming support and conversation history.
Uses API key authentication. Routes through Langflow (chat_service.langflow_chat).
"""
import json
from typing import Optional, Any, Dict

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger
from auth_context import set_search_filters, set_search_limit, set_score_threshold, set_auth_context
from dependencies import get_chat_service, get_session_manager, get_api_key_user_async
from session_manager import User

logger = get_logger(__name__)


class ChatV1Body(BaseModel):
    message: str
    stream: bool = False
    chat_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: Optional[str] = None


async def _transform_stream_to_sse(raw_stream, chat_id_container: dict):
    """Transform raw Langflow streaming format to clean SSE events for v1 API."""
    full_text = ""
    chat_id = None

    async for chunk in raw_stream:
        try:
            if isinstance(chunk, bytes):
                chunk_str = chunk.decode("utf-8").strip()
            else:
                chunk_str = str(chunk).strip()

            if not chunk_str:
                continue

            chunk_data = json.loads(chunk_str)
            delta_text = ""

            if "delta" in chunk_data:
                delta = chunk_data["delta"]
                if isinstance(delta, dict):
                    delta_text = delta.get("content", "") or delta.get("text", "")
                elif isinstance(delta, str):
                    delta_text = delta

            if not delta_text and chunk_data.get("output_text"):
                delta_text = chunk_data["output_text"]
            if not delta_text and chunk_data.get("text"):
                delta_text = chunk_data["text"]
            if not delta_text and chunk_data.get("content"):
                delta_text = chunk_data["content"]

            if delta_text:
                full_text += delta_text
                yield f"data: {json.dumps({'type': 'content', 'delta': delta_text})}\n\n"

            if not chat_id:
                chat_id = chunk_data.get("id") or chunk_data.get("response_id")

        except json.JSONDecodeError:
            if chunk_str:
                yield f"data: {json.dumps({'type': 'content', 'delta': chunk_str})}\n\n"
                full_text += chunk_str
        except Exception as e:
            logger.warning("Error processing stream chunk", error=str(e))

    yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
    chat_id_container["chat_id"] = chat_id


async def chat_create_endpoint(
    body: ChatV1Body,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """Send a chat message via Langflow. POST /v1/chat"""
    message = body.message.strip()
    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    user_id = user.user_id
    jwt_token = user.jwt_token

    if body.filters:
        set_search_filters(body.filters)
    set_search_limit(body.limit)
    set_score_threshold(body.score_threshold)
    set_auth_context(user_id, jwt_token)

    if body.stream:
        raw_stream = await chat_service.langflow_chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=body.chat_id,
            stream=True,
            filter_id=body.filter_id,
        )
        chat_id_container = {}
        return StreamingResponse(
            _transform_stream_to_sse(raw_stream, chat_id_container),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    else:
        result = await chat_service.langflow_chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=body.chat_id,
            stream=False,
            filter_id=body.filter_id,
        )
        return JSONResponse({
            "response": result.get("response", ""),
            "chat_id": result.get("response_id"),
            "sources": result.get("sources", []),
        })


async def chat_list_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_api_key_user_async),
):
    """List all conversations for the authenticated user. GET /v1/chat"""
    try:
        history = await chat_service.get_langflow_history(user.user_id)
        conversations = [
            {
                "chat_id": conv.get("response_id"),
                "title": conv.get("title", ""),
                "created_at": conv.get("created_at"),
                "last_activity": conv.get("last_activity"),
                "message_count": conv.get("total_messages", 0),
            }
            for conv in history.get("conversations", [])
        ]
        return JSONResponse({"conversations": conversations})
    except Exception as e:
        logger.error("Failed to list conversations", error=str(e), user_id=user.user_id)
        return JSONResponse({"error": f"Failed to list conversations: {str(e)}"}, status_code=500)


async def chat_get_endpoint(
    chat_id: str,
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_api_key_user_async),
):
    """Get a specific conversation with full message history. GET /v1/chat/{chat_id}"""
    try:
        history = await chat_service.get_langflow_history(user.user_id)

        conversation = None
        for conv in history.get("conversations", []):
            if conv.get("response_id") == chat_id:
                conversation = conv
                break

        if not conversation:
            return JSONResponse({"error": "Conversation not found"}, status_code=404)

        # Transform to public API format
        messages = []
        for msg in conversation.get("messages", []):
            message_data = {
                "role": msg.get("role"),
                "content": msg.get("content"),
                "timestamp": msg.get("timestamp"),
            }
            # Include token usage if available (from Responses API)
            usage = msg.get("response_data", {}).get("usage") if isinstance(msg.get("response_data"), dict) else None
            if usage:
                message_data["usage"] = usage
            messages.append(message_data)

        return JSONResponse({
            "chat_id": conversation.get("response_id"),
            "title": conversation.get("title", ""),
            "created_at": conversation.get("created_at"),
            "last_activity": conversation.get("last_activity"),
            "messages": messages,
        })
    except Exception as e:
        logger.error("Failed to get conversation", error=str(e), user_id=user.user_id, chat_id=chat_id)
        return JSONResponse({"error": f"Failed to get conversation: {str(e)}"}, status_code=500)


async def chat_delete_endpoint(
    chat_id: str,
    chat_service=Depends(get_chat_service),
    user: User = Depends(get_api_key_user_async),
):
    """Delete a conversation. DELETE /v1/chat/{chat_id}"""
    try:
        result = await chat_service.delete_session(user.user_id, chat_id)
        if result.get("success"):
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"error": result.get("error", "Failed to delete conversation")},
                status_code=500,
            )
    except Exception as e:
        logger.error("Failed to delete conversation", error=str(e), user_id=user.user_id, chat_id=chat_id)
        return JSONResponse({"error": f"Failed to delete conversation: {str(e)}"}, status_code=500)
