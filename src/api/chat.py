from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse


async def chat_endpoint(request: Request, chat_service, session_manager):
    """Handle chat requests"""
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)
    filters = data.get("filters")
    limit = data.get("limit", 10)
    score_threshold = data.get("scoreThreshold", 0)

    user = request.state.user
    user_id = user.user_id

    # Get JWT token from auth middleware
    jwt_token = request.state.jwt_token

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    # Set context variables for search tool (similar to search endpoint)
    if filters:
        from auth_context import set_search_filters

        set_search_filters(filters)

    from auth_context import set_search_limit, set_score_threshold

    set_search_limit(limit)
    set_score_threshold(score_threshold)

    if stream:
        return StreamingResponse(
            await chat_service.chat(
                prompt,
                user_id,
                jwt_token,
                previous_response_id=previous_response_id,
                stream=True,
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
            prompt,
            user_id,
            jwt_token,
            previous_response_id=previous_response_id,
            stream=False,
        )
        return JSONResponse(result)


async def langflow_endpoint(request: Request, chat_service, session_manager):
    """Handle Langflow chat requests"""
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)
    filters = data.get("filters")
    limit = data.get("limit", 10)
    score_threshold = data.get("scoreThreshold", 0)

    user = request.state.user
    user_id = user.user_id

    # Get JWT token from auth middleware
    jwt_token = request.state.jwt_token

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    # Set context variables for search tool (similar to chat endpoint)
    if filters:
        from auth_context import set_search_filters

        set_search_filters(filters)

    from auth_context import set_search_limit, set_score_threshold

    set_search_limit(limit)
    set_score_threshold(score_threshold)

    try:
        if stream:
            return StreamingResponse(
                await chat_service.langflow_chat(
                    prompt,
                    user_id,
                    jwt_token,
                    previous_response_id=previous_response_id,
                    stream=True,
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
                prompt,
                user_id,
                jwt_token,
                previous_response_id=previous_response_id,
                stream=False,
            )
            return JSONResponse(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"[ERROR] Langflow request failed: {str(e)}")
        return JSONResponse(
            {"error": f"Langflow request failed: {str(e)}"}, status_code=500
        )


async def chat_history_endpoint(request: Request, chat_service, session_manager):
    """Get chat history for a user"""
    user = request.state.user
    user_id = user.user_id

    try:
        history = await chat_service.get_chat_history(user_id)
        return JSONResponse(history)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get chat history: {str(e)}"}, status_code=500
        )


async def langflow_history_endpoint(request: Request, chat_service, session_manager):
    """Get langflow chat history for a user"""
    user = request.state.user
    user_id = user.user_id

    try:
        history = await chat_service.get_langflow_history(user_id)
        return JSONResponse(history)
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to get langflow history: {str(e)}"}, status_code=500
        )
