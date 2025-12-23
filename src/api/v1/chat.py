"""
Public API v1 Chat endpoint.

Provides chat functionality with streaming support and conversation history.
Uses API key authentication. Routes through Langflow (chat_service.langflow_chat).
"""
import json
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger
from auth_context import set_search_filters, set_search_limit, set_score_threshold, set_auth_context

logger = get_logger(__name__)


async def _transform_stream_to_sse(raw_stream, chat_id_container: dict):
    """
    Transform the raw Langflow streaming format to clean SSE events for v1 API.

    Yields SSE events in the format:
        data: {"type": "content", "delta": "..."}
        data: {"type": "sources", "sources": [...]}
        data: {"type": "done", "chat_id": "..."}
    """
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

            # Extract text from various possible formats
            delta_text = ""

            # Format 1: delta.content (OpenAI-style)
            if "delta" in chunk_data:
                delta = chunk_data["delta"]
                if isinstance(delta, dict):
                    delta_text = delta.get("content", "") or delta.get("text", "")
                elif isinstance(delta, str):
                    delta_text = delta

            # Format 2: output_text (Langflow-style)
            if not delta_text and chunk_data.get("output_text"):
                delta_text = chunk_data["output_text"]

            # Format 3: text field directly
            if not delta_text and chunk_data.get("text"):
                delta_text = chunk_data["text"]

            # Format 4: content field directly
            if not delta_text and chunk_data.get("content"):
                delta_text = chunk_data["content"]

            if delta_text:
                full_text += delta_text
                yield f"data: {json.dumps({'type': 'content', 'delta': delta_text})}\n\n"

            # Extract chat_id/response_id from various fields
            if not chat_id:
                chat_id = chunk_data.get("id") or chunk_data.get("response_id")

        except json.JSONDecodeError:
            # Raw text without JSON wrapper
            if chunk_str:
                yield f"data: {json.dumps({'type': 'content', 'delta': chunk_str})}\n\n"
                full_text += chunk_str
        except Exception as e:
            logger.warning("Error processing stream chunk", error=str(e), chunk=chunk_str[:100] if chunk_str else "")

    yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
    chat_id_container["chat_id"] = chat_id


async def chat_create_endpoint(request: Request, chat_service, session_manager):
    """
    Send a chat message via Langflow.

    POST /v1/chat
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    message = data.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    stream = data.get("stream", False)
    chat_id = data.get("chat_id")
    filters = data.get("filters")
    limit = data.get("limit", 10)
    score_threshold = data.get("score_threshold", 0)
    filter_id = data.get("filter_id")

    user = request.state.user
    user_id = user.user_id
    jwt_token = session_manager.get_effective_jwt_token(user_id, None)

    # Set context variables for search tool
    if filters:
        set_search_filters(filters)
    set_search_limit(limit)
    set_score_threshold(score_threshold)
    set_auth_context(user_id, jwt_token)

    if stream:
        raw_stream = await chat_service.langflow_chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=chat_id,
            stream=True,
            filter_id=filter_id,
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
            previous_response_id=chat_id,
            stream=False,
            filter_id=filter_id,
        )
        # Transform response_id to chat_id for v1 API format
        return JSONResponse({
            "response": result.get("response", ""),
            "chat_id": result.get("response_id"),
            "sources": result.get("sources", []),
        })


async def chat_list_endpoint(request: Request, chat_service, session_manager):
    """
    List all conversations for the authenticated user.

    GET /v1/chat

    Response:
        {
            "conversations": [
                {
                    "chat_id": "...",
                    "title": "What is RAG?",
                    "created_at": "...",
                    "last_activity": "...",
                    "message_count": 5
                }
            ]
        }
    """
    user = request.state.user
    user_id = user.user_id

    try:
        # Get Langflow chat history (since v1 routes through Langflow)
        history = await chat_service.get_langflow_history(user_id)

        # Transform to public API format
        conversations = []
        for conv in history.get("conversations", []):
            conversations.append({
                "chat_id": conv.get("response_id"),
                "title": conv.get("title", ""),
                "created_at": conv.get("created_at"),
                "last_activity": conv.get("last_activity"),
                "message_count": conv.get("total_messages", 0),
            })

        return JSONResponse({"conversations": conversations})

    except Exception as e:
        logger.error("Failed to list conversations", error=str(e), user_id=user_id)
        return JSONResponse(
            {"error": f"Failed to list conversations: {str(e)}"},
            status_code=500,
        )


async def chat_get_endpoint(request: Request, chat_service, session_manager):
    """
    Get a specific conversation with full message history.

    GET /v1/chat/{chat_id}

    Response:
        {
            "chat_id": "...",
            "title": "What is RAG?",
            "created_at": "...",
            "last_activity": "...",
            "messages": [
                {"role": "user", "content": "What is RAG?", "timestamp": "..."},
                {"role": "assistant", "content": "RAG stands for...", "timestamp": "..."}
            ]
        }
    """
    user = request.state.user
    user_id = user.user_id
    chat_id = request.path_params.get("chat_id")

    if not chat_id:
        return JSONResponse(
            {"error": "Chat ID is required"},
            status_code=400,
        )

    try:
        # Get Langflow chat history and find the specific conversation
        history = await chat_service.get_langflow_history(user_id)

        conversation = None
        for conv in history.get("conversations", []):
            if conv.get("response_id") == chat_id:
                conversation = conv
                break

        if not conversation:
            return JSONResponse(
                {"error": "Conversation not found"},
                status_code=404,
            )

        # Transform to public API format
        messages = []
        for msg in conversation.get("messages", []):
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "timestamp": msg.get("timestamp"),
            })

        response_data = {
            "chat_id": conversation.get("response_id"),
            "title": conversation.get("title", ""),
            "created_at": conversation.get("created_at"),
            "last_activity": conversation.get("last_activity"),
            "messages": messages,
        }

        return JSONResponse(response_data)

    except Exception as e:
        logger.error("Failed to get conversation", error=str(e), user_id=user_id, chat_id=chat_id)
        return JSONResponse(
            {"error": f"Failed to get conversation: {str(e)}"},
            status_code=500,
        )


async def chat_delete_endpoint(request: Request, chat_service, session_manager):
    """
    Delete a conversation.

    DELETE /v1/chat/{chat_id}

    Response:
        {"success": true}
    """
    user = request.state.user
    user_id = user.user_id
    chat_id = request.path_params.get("chat_id")

    if not chat_id:
        return JSONResponse(
            {"error": "Chat ID is required"},
            status_code=400,
        )

    try:
        result = await chat_service.delete_session(user_id, chat_id)

        if result.get("success"):
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"error": result.get("error", "Failed to delete conversation")},
                status_code=500,
            )

    except Exception as e:
        logger.error("Failed to delete conversation", error=str(e), user_id=user_id, chat_id=chat_id)
        return JSONResponse(
            {"error": f"Failed to delete conversation: {str(e)}"},
            status_code=500,
        )
