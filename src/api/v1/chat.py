"""
Public API v1 Chat endpoint.

Provides chat functionality with streaming support and conversation history.
Uses API key authentication. Routes through Langflow endpoint.
"""
import json
from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from api.chat import langflow_endpoint

logger = get_logger(__name__)


def _transform_v1_request_to_internal(data: dict) -> dict:
    """Transform v1 API request format to internal Langflow format."""
    return {
        "prompt": data.get("message", ""),  # v1 uses "message", internal uses "prompt"
        "previous_response_id": data.get("chat_id"),  # v1 uses "chat_id"
        "stream": data.get("stream", False),
        "filters": data.get("filters"),
        "limit": data.get("limit", 10),
        "scoreThreshold": data.get("score_threshold", 0),  # v1 uses snake_case
        "filter_id": data.get("filter_id"),
    }


async def chat_create_endpoint(request: Request, chat_service, session_manager):
    """
    Send a chat message. Routes to internal Langflow endpoint.

    POST /v1/chat - see internal /langflow endpoint for full documentation.
    Transforms v1 format (message, chat_id, score_threshold) to internal format.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    message = data.get("message", "").strip()
    if not message:
        return JSONResponse(
            {"error": "Message is required"},
            status_code=400,
        )

    # Transform v1 request to internal format
    internal_data = _transform_v1_request_to_internal(data)

    # Create a new request with transformed body for the internal endpoint
    body = json.dumps(internal_data).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    internal_request = Request(request.scope, receive)
    internal_request.state = request.state  # Copy state for auth

    # Call internal Langflow endpoint
    return await langflow_endpoint(internal_request, chat_service, session_manager)


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
