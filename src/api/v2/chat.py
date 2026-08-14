"""
Public API v2 Chat endpoint.

Provides chat functionality with streaming support, conversation history, and
IBM Watson Orchestrate citation output formatting (search_results and citations_shown: -1).
"""

import time

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.v1._filter_resolution import merge_filter_overrides, resolve_filter_id
from api.v1.chat import (
    ChatV1Body,
    _openrag_user_id,
    _transform_stream_to_sse,
    chat_delete_endpoint,
    chat_get_endpoint,
    chat_list_endpoint,
)
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


def _build_search_results(sources: list) -> list[dict]:
    """Transform OpenRAG sources to IBM Watson Orchestrate search_results citation format."""
    search_results = []
    for s in sources:
        if isinstance(s, dict):
            search_results.append(
                {
                    "title": s.get("filename") or "Document",
                    "body": s.get("text", ""),
                    "url": s.get("source_url") or s.get("url") or "",
                }
            )
    return search_results


async def chat_v2_create_endpoint(
    body: ChatV1Body,
    request: Request,
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_api_key_permission("chat:use")),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
):
    """Send a chat message via Langflow with citation artifact capability. POST /v2/chat"""
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
        resolved_filters, resolved_limit, resolved_score_threshold = merge_filter_overrides(
            resolved, body
        )

    if resolved_filters:
        set_search_filters(resolved_filters)
    set_search_limit(resolved_limit)
    set_score_threshold(resolved_score_threshold)
    set_auth_context(user_id, jwt_token)
    start = time.perf_counter()

    logger.info(
        "[CHAT V2] Request started",
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
            "[CHAT V2] Stream initialized",
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
        sources = result.get("sources", [])
        search_results = _build_search_results(sources)

        logger.info(
            "[CHAT V2] Request completed",
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start) * 1000),
            response_id=result.get("response_id"),
            source_count=len(sources),
        )
        return JSONResponse(
            {
                "response": result.get("response", ""),
                "chat_id": result.get("response_id"),
                "sources": sources,
                "search_results": search_results,
                "citations_shown": -1,
            }
        )
