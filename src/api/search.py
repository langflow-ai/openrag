from starlette.requests import Request
from starlette.responses import JSONResponse

async def search(request: Request, search_service, session_manager):
    """Search for documents"""
    payload = await request.json()
    query = payload.get("query")
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)
    
    filters = payload.get("filters", {})  # Optional filters, defaults to empty dict
    limit = payload.get("limit", 10)  # Optional limit, defaults to 10
    score_threshold = payload.get("scoreThreshold", 0)  # Optional score threshold, defaults to 0
    
    user = request.state.user
    # Extract JWT token from cookie for OpenSearch OIDC auth
    jwt_token = request.cookies.get("auth_token")
    
    result = await search_service.search(query, user_id=user.user_id, jwt_token=jwt_token, filters=filters, limit=limit, score_threshold=score_threshold)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)