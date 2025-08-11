from starlette.requests import Request
from starlette.responses import JSONResponse

async def search(request: Request, search_service, session_manager):
    """Search for documents"""
    payload = await request.json()
    query = payload.get("query")
    if not query:
        return JSONResponse({"error": "Query is required"}, status_code=400)
    
    user = request.state.user
    # Extract JWT token from cookie for OpenSearch OIDC auth
    jwt_token = request.cookies.get("auth_token")
    
    result = await search_service.search(query, user_id=user.user_id, jwt_token=jwt_token)
    return JSONResponse(result)