from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

async def chat_endpoint(request: Request, chat_service, session_manager):
    """Handle chat requests"""
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)
    
    user = request.state.user
    user_id = user.user_id
    
    # Get JWT token from request cookie
    jwt_token = request.cookies.get("auth_token")

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    if stream:
        return StreamingResponse(
            await chat_service.chat(prompt, user_id, jwt_token, previous_response_id=previous_response_id, stream=True),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control"
            }
        )
    else:
        result = await chat_service.chat(prompt, user_id, jwt_token, previous_response_id=previous_response_id, stream=False)
        return JSONResponse(result)

async def langflow_endpoint(request: Request, chat_service, session_manager):
    """Handle Langflow chat requests"""
    data = await request.json()
    prompt = data.get("prompt", "")
    previous_response_id = data.get("previous_response_id")
    stream = data.get("stream", False)
    
    # Get JWT token from request cookie
    jwt_token = request.cookies.get("auth_token")
    
    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    try:
        if stream:
            return StreamingResponse(
                await chat_service.langflow_chat(prompt, jwt_token, previous_response_id=previous_response_id, stream=True),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control"
                }
            )
        else:
            result = await chat_service.langflow_chat(prompt, jwt_token, previous_response_id=previous_response_id, stream=False)
            return JSONResponse(result)
        
    except Exception as e:
        return JSONResponse({"error": f"Langflow request failed: {str(e)}"}, status_code=500)