"""
Public API v1 Chat endpoint.

Provides chat functionality with streaming support and conversation history.
Uses API key authentication. Routes through Langflow (chat_service.langflow_chat).
"""

import json
import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from api.v1._filter_resolution import resolve_filter_id
from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from dependencies import (
    get_chat_service,
    get_knowledge_filter_service,
    get_session_manager,
    require_api_key_permission,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _openrag_user_id(user: User) -> str:
    return getattr(user, "db_user_id", None) or user.user_id


class ChatV1Body(BaseModel):
    message: str
    stream: bool = False
    chat_id: str | None = None
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0
    filter_id: str | None = None


def _extract_sources(item: dict) -> list[dict]:
    """Extract sources from a retrieval tool call item."""
    sources = []
    for result in item.get("results", []):
        if isinstance(result, dict) and "text" in result:
            sources.append(
                {
                    "filename": result.get("filename", ""),
                    "text": result.get("text", ""),
                    "score": result.get("score", 0),
                    "page": result.get("page"),
                    "mimetype": result.get("mimetype"),
                }
            )
    return sources


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

            # Emit sources from retrieval tool calls
            item = chunk_data.get("item", {})
            if item.get("type") in ("retrieval_call", "tool_call") and item.get("results"):
                sources = _extract_sources(item)
                if sources:
                    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

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
    request: Request,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_api_key_permission("chat:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Send a chat message via Langflow. POST /v1/chat"""
    message = body.message.strip()
    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    user_id = user.user_id
    storage_user_id = _openrag_user_id(user)
    jwt_token = user.jwt_token
    request_id = request.headers.get("x-request-id")
    if body.chat_id:
        from api.chat import _assert_owns

        await _assert_owns(body.chat_id, storage_user_id)

    resolved_filters = body.filters
    resolved_limit = body.limit
    resolved_score_threshold = body.score_threshold
    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=jwt_token,
        )
        # Inline values override per-field; defaults (10 / 0) fall back to the filter.
        if not body.filters:
            resolved_filters = resolved["filters"]
        if body.limit == 10:
            resolved_limit = resolved["limit"]
        if body.score_threshold == 0:
            resolved_score_threshold = resolved["score_threshold"]

    if resolved_filters:
        set_search_filters(resolved_filters)
    set_search_limit(resolved_limit)
    set_score_threshold(resolved_score_threshold)
    set_auth_context(user_id, jwt_token)
    start = time.perf_counter()

    logger.info(
        "[CHAT V1] Request started",
        request_id=request_id,
        stream=body.stream,
        has_chat_id=bool(body.chat_id),
        filter_id=body.filter_id,
    )

    if body.stream:
        raw_stream = await chat_service.langflow_chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=body.chat_id,
            stream=True,
            filter_id=body.filter_id,
            owner=user.user_id,
            owner_name=user.name,
            owner_email=user.email,
            storage_user_id=storage_user_id,
        )
        logger.info(
            "[CHAT V1] Stream initialized",
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start) * 1000),
        )
        chat_id_container: dict[str, str] = {}
        return StreamingResponse(
            _transform_stream_to_sse(raw_stream, chat_id_container),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        result = await chat_service.langflow_chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=body.chat_id,
            stream=False,
            filter_id=body.filter_id,
            owner=user.user_id,
            owner_name=user.name,
            owner_email=user.email,
            storage_user_id=storage_user_id,
        )
        logger.info(
            "[CHAT V1] Request completed",
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start) * 1000),
            response_id=result.get("response_id"),
            source_count=len(result.get("sources", [])),
        )
        return JSONResponse(
            {
                "response": result.get("response", ""),
                "chat_id": result.get("response_id"),
                "sources": result.get("sources", []),
            }
        )


async def chat_list_endpoint(
    chat_service=Depends(get_chat_service),
    user: User = Depends(require_api_key_permission("conversations:read:own")),
):
    """List all conversations for the authenticated user. GET /v1/chat"""
    try:
        history = await chat_service.get_langflow_history(_openrag_user_id(user))
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
    user: User = Depends(require_api_key_permission("conversations:read:own")),
):
    """Get a specific conversation with full message history. GET /v1/chat/{chat_id}"""
    try:
        history = await chat_service.get_langflow_history(_openrag_user_id(user))

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
            usage = (
                msg.get("response_data", {}).get("usage")
                if isinstance(msg.get("response_data"), dict)
                else None
            )
            if usage:
                message_data["usage"] = usage
            messages.append(message_data)

        return JSONResponse(
            {
                "chat_id": conversation.get("response_id"),
                "title": conversation.get("title", ""),
                "created_at": conversation.get("created_at"),
                "last_activity": conversation.get("last_activity"),
                "messages": messages,
            }
        )
    except Exception as e:
        logger.error(
            "Failed to get conversation", error=str(e), user_id=user.user_id, chat_id=chat_id
        )
        return JSONResponse({"error": f"Failed to get conversation: {str(e)}"}, status_code=500)


async def chat_delete_endpoint(
    chat_id: str,
    chat_service=Depends(get_chat_service),
    user: User = Depends(require_api_key_permission("conversations:delete:own")),
):
    """Delete a conversation. DELETE /v1/chat/{chat_id}"""
    try:
        from api.chat import _assert_owns

        storage_user_id = _openrag_user_id(user)
        await _assert_owns(chat_id, storage_user_id)
        result = await chat_service.delete_session(storage_user_id, chat_id)
        if result.get("not_found"):
            return JSONResponse({"error": "Conversation not found"}, status_code=404)
        if result.get("success"):
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"error": result.get("error", "Failed to delete conversation")},
                status_code=500,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete conversation", error=str(e), user_id=user.user_id, chat_id=chat_id
        )
        return JSONResponse({"error": f"Failed to delete conversation: {str(e)}"}, status_code=500)
