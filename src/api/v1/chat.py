"""
Public API v1 Chat endpoint.

Provides chat functionality with streaming support and conversation history.
Uses API key authentication.
"""
import json
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger
from auth_context import set_search_filters, set_search_limit, set_score_threshold, set_auth_context

logger = get_logger(__name__)


async def _transform_stream_to_sse(raw_stream, chat_id_container: dict):
    """
    Transform the raw internal streaming format to clean SSE events.

    Yields SSE events in the format:
        event: content
        data: {"type": "content", "delta": "..."}

        event: sources
        data: {"type": "sources", "sources": [...]}

        event: done
        data: {"type": "done", "chat_id": "..."}
    """
    full_text = ""
    sources = []
    chat_id = None

    async for chunk in raw_stream:
        try:
            # Decode the chunk
            if isinstance(chunk, bytes):
                chunk_str = chunk.decode("utf-8").strip()
            else:
                chunk_str = str(chunk).strip()

            if not chunk_str:
                continue

            # Parse the JSON chunk
            chunk_data = json.loads(chunk_str)

            # Extract text delta
            delta_text = None
            if "delta" in chunk_data:
                delta = chunk_data["delta"]
                if isinstance(delta, dict):
                    delta_text = delta.get("content") or delta.get("text") or ""
                elif isinstance(delta, str):
                    delta_text = delta

            if "output_text" in chunk_data and chunk_data["output_text"]:
                delta_text = chunk_data["output_text"]

            # Yield content event if we have text
            if delta_text:
                full_text += delta_text
                event = {"type": "content", "delta": delta_text}
                yield f"event: content\ndata: {json.dumps(event)}\n\n"

            # Extract chat_id/response_id
            if "id" in chunk_data and chunk_data["id"]:
                chat_id = chunk_data["id"]
            elif "response_id" in chunk_data and chunk_data["response_id"]:
                chat_id = chunk_data["response_id"]

            # Extract sources from tool call results
            if "item" in chunk_data and isinstance(chunk_data["item"], dict):
                item = chunk_data["item"]
                if item.get("type") in ("retrieval_call", "tool_call", "function_call"):
                    results = item.get("results", [])
                    if results:
                        for result in results:
                            if isinstance(result, dict):
                                source = {
                                    "filename": result.get("filename", result.get("title", "Unknown")),
                                    "text": result.get("text", result.get("content", "")),
                                    "score": result.get("score", 0),
                                    "page": result.get("page"),
                                }
                                sources.append(source)

        except json.JSONDecodeError:
            # Not JSON, might be raw text
            if chunk_str and not chunk_str.startswith("{"):
                event = {"type": "content", "delta": chunk_str}
                yield f"event: content\ndata: {json.dumps(event)}\n\n"
                full_text += chunk_str
        except Exception as e:
            logger.warning("Error processing stream chunk", error=str(e))
            continue

    # Yield sources event if we have any
    if sources:
        event = {"type": "sources", "sources": sources}
        yield f"event: sources\ndata: {json.dumps(event)}\n\n"

    # Yield done event with chat_id
    event = {"type": "done", "chat_id": chat_id}
    yield f"event: done\ndata: {json.dumps(event)}\n\n"

    # Store chat_id for caller
    chat_id_container["chat_id"] = chat_id


async def chat_create_endpoint(request: Request, chat_service, session_manager):
    """
    Send a chat message.

    POST /api/v1/chat

    Request body:
        {
            "message": "What is RAG?",
            "stream": false,  // optional, default false
            "chat_id": "...",  // optional, to continue conversation
            "filters": {...},  // optional
            "limit": 10,  // optional
            "score_threshold": 0.5  // optional
        }

    Non-streaming response:
        {
            "response": "RAG stands for...",
            "chat_id": "chat_xyz789",
            "sources": [...]
        }

    Streaming response (SSE):
        event: content
        data: {"type": "content", "delta": "RAG stands for"}

        event: sources
        data: {"type": "sources", "sources": [...]}

        event: done
        data: {"type": "done", "chat_id": "chat_xyz789"}
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

    stream = data.get("stream", False)
    chat_id = data.get("chat_id")  # For conversation continuation
    filters = data.get("filters")
    limit = data.get("limit", 10)
    score_threshold = data.get("score_threshold", 0)

    user = request.state.user
    user_id = user.user_id

    # Note: API key auth doesn't have JWT, so we pass None
    jwt_token = None

    # Set context variables for search tool
    if filters:
        set_search_filters(filters)
    set_search_limit(limit)
    set_score_threshold(score_threshold)
    set_auth_context(user_id, jwt_token)

    if stream:
        # Streaming response
        raw_stream = await chat_service.chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=chat_id,
            stream=True,
        )

        chat_id_container = {}

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
        # Non-streaming response
        result = await chat_service.chat(
            prompt=message,
            user_id=user_id,
            jwt_token=jwt_token,
            previous_response_id=chat_id,
            stream=False,
        )

        # Transform response to public API format
        # Internal format: {"response": "...", "response_id": "..."}
        response_data = {
            "response": result.get("response", ""),
            "chat_id": result.get("response_id"),
            "sources": result.get("sources", []),
        }

        return JSONResponse(response_data)


async def chat_list_endpoint(request: Request, chat_service, session_manager):
    """
    List all conversations for the authenticated user.

    GET /api/v1/chat

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
        # Get chat history
        history = await chat_service.get_chat_history(user_id)

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

    GET /api/v1/chat/{chat_id}

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
        # Get chat history and find the specific conversation
        history = await chat_service.get_chat_history(user_id)

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

    DELETE /api/v1/chat/{chat_id}

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
