from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


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

    jwt_token = session_manager.get_effective_jwt_token(user_id, request.state.jwt_token)

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

    jwt_token = session_manager.get_effective_jwt_token(user_id, request.state.jwt_token)

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
        logger.error("Langflow request failed", error=str(e))
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


async def onboarding_chat_endpoint(request: Request, session_manager):
    """Handle onboarding chat requests with tweaks support"""
    from config.settings import LANGFLOW_URL, LANGFLOW_CHAT_FLOW_ID, clients
    import json as json_lib

    data = await request.json()
    prompt = data.get("prompt", "")
    tweaks = data.get("tweaks")
    stream = data.get("stream", False)

    user = request.state.user
    user_id = user.user_id

    jwt_token = session_manager.get_effective_jwt_token(user_id, request.state.jwt_token)

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    if not LANGFLOW_URL or not LANGFLOW_CHAT_FLOW_ID:
        return JSONResponse(
            {"error": "Langflow not configured"}, status_code=500
        )

    try:
        # Build payload like langflow_file_service does
        payload = {
            "input_value": prompt,
            "input_type": "chat",
            "output_type": "text",
        }

        if tweaks:
            payload["tweaks"] = tweaks
            logger.info("Onboarding chat with tweaks", tweaks_keys=list(tweaks.keys()))

        headers = {}
        if jwt_token:
            headers["X-Langflow-Global-Var-JWT"] = jwt_token

        # Use the lower-level langflow_request API
        if stream:
            # For streaming, we need to handle SSE from Langflow
            async def stream_generator():
                # Build the full URL and headers for the streaming request
                from config.settings import generate_langflow_api_key

                api_key = await generate_langflow_api_key()
                if not api_key:
                    yield json_lib.dumps({"error": "No API key available"}).encode()
                    return

                # Merge headers
                stream_headers = {
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                    **headers
                }

                endpoint = f"{LANGFLOW_URL}/api/v1/run/{LANGFLOW_CHAT_FLOW_ID}?stream=true"

                logger.info("Starting stream request", endpoint=endpoint, payload=payload)

                async with clients.langflow_http_client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=stream_headers,
                ) as resp:
                    logger.info("Stream response received", status_code=resp.status_code)

                    if resp.status_code >= 400:
                        logger.error(
                            "Onboarding chat failed",
                            status_code=resp.status_code,
                        )
                        yield json_lib.dumps({"error": "Request failed"}).encode()
                        return

                    # Stream the response line by line
                    logger.info("Starting to iterate response lines")
                    previous_text = ""
                    async for line in resp.aiter_lines():
                        if line:
                            logger.info("Streaming line received", line=line[:500], full_line=line)
                            try:
                                # Parse Langflow event format
                                event_data = json_lib.loads(line)
                                logger.info("Parsed event", event_type=event_data.get("event"), event_data=event_data.get("data"))

                                if event_data.get("event") == "add_message":
                                    data = event_data.get("data", {})
                                    current_text = data.get("text", "")
                                    logger.info("Current text from event", text=current_text, text_length=len(current_text))

                                    # Only send delta if text changed
                                    if current_text and current_text != previous_text:
                                        # Calculate the delta (new content)
                                        delta_content = current_text[len(previous_text):]
                                        previous_text = current_text

                                        # Format as expected by frontend (matching chat page format)
                                        chunk = {
                                            "object": "response.chunk",
                                            "delta": {"content": delta_content}
                                        }
                                        yield json_lib.dumps(chunk).encode() + b"\n"
                                        logger.info("Sent delta", delta=delta_content[:100])
                                    else:
                                        logger.info("Skipping delta - no text or same as previous", current_empty=not current_text, same_as_previous=current_text == previous_text)
                            except json_lib.JSONDecodeError as e:
                                logger.error("Failed to parse streaming line", error=str(e), line=line[:200])

                    logger.info("Finished streaming response")

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control",
                },
            )
        else:
            # Non-streaming request
            resp = await clients.langflow_request(
                "POST",
                f"/api/v1/run/{LANGFLOW_CHAT_FLOW_ID}",
                json=payload,
                headers=headers,
            )

            if resp.status_code >= 400:
                logger.error(
                    "Onboarding chat failed",
                    status_code=resp.status_code,
                    body=resp.text[:500],
                )
                return JSONResponse(
                    {"error": "Request failed"}, status_code=resp.status_code
                )

            result = resp.json()
            return JSONResponse(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error("Onboarding chat request failed", error=str(e))
        return JSONResponse(
            {"error": f"Request failed: {str(e)}"}, status_code=500
        )


async def delete_session_endpoint(request: Request, chat_service, session_manager):
    """Delete a chat session"""
    user = request.state.user
    user_id = user.user_id
    session_id = request.path_params["session_id"]

    try:
        # Delete from both local storage and Langflow
        result = await chat_service.delete_session(user_id, session_id)

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
