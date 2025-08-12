from starlette.requests import Request
from starlette.responses import JSONResponse
import uuid
from datetime import datetime

async def create_context(request: Request, contexts_service, session_manager):
    """Create a new search context"""
    payload = await request.json()
    
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "Context name is required"}, status_code=400)
    
    description = payload.get("description", "")
    query_data = payload.get("queryData")
    if not query_data:
        return JSONResponse({"error": "Query data is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    # Create context document
    context_id = str(uuid.uuid4())
    context_doc = {
        "id": context_id,
        "name": name,
        "description": description,
        "query_data": query_data,  # Store the full search query JSON
        "owner": user.user_id,
        "allowed_users": payload.get("allowedUsers", []),  # ACL field for future use
        "allowed_groups": payload.get("allowedGroups", []),  # ACL field for future use
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    result = await contexts_service.create_context(context_doc, user_id=user.user_id, jwt_token=jwt_token)
    return JSONResponse(result)

async def search_contexts(request: Request, contexts_service, session_manager):
    """Search for contexts by name, description, or query content"""
    payload = await request.json()
    
    query = payload.get("query", "")
    limit = payload.get("limit", 20)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await contexts_service.search_contexts(query, user_id=user.user_id, jwt_token=jwt_token, limit=limit)
    return JSONResponse(result)

async def get_context(request: Request, contexts_service, session_manager):
    """Get a specific context by ID"""
    context_id = request.path_params.get("context_id")
    if not context_id:
        return JSONResponse({"error": "Context ID is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await contexts_service.get_context(context_id, user_id=user.user_id, jwt_token=jwt_token)
    return JSONResponse(result)

async def update_context(request: Request, contexts_service, session_manager):
    """Update an existing context by delete + recreate (due to DLS limitations)"""
    context_id = request.path_params.get("context_id")
    if not context_id:
        return JSONResponse({"error": "Context ID is required"}, status_code=400)
    
    payload = await request.json()
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    # First, get the existing context
    existing_result = await contexts_service.get_context(context_id, user_id=user.user_id, jwt_token=jwt_token)
    if not existing_result.get("success"):
        return JSONResponse({"error": "Context not found or access denied"}, status_code=404)
    
    existing_context = existing_result["context"]
    
    # Delete the existing context
    delete_result = await contexts_service.delete_context(context_id, user_id=user.user_id, jwt_token=jwt_token)
    if not delete_result.get("success"):
        return JSONResponse({"error": "Failed to delete existing context"}, status_code=500)
    
    # Create updated context document with same ID
    updated_context = {
        "id": context_id,
        "name": payload.get("name", existing_context["name"]),
        "description": payload.get("description", existing_context["description"]),
        "query_data": payload.get("queryData", existing_context["query_data"]),
        "owner": existing_context["owner"],
        "allowed_users": payload.get("allowedUsers", existing_context.get("allowed_users", [])),
        "allowed_groups": payload.get("allowedGroups", existing_context.get("allowed_groups", [])),
        "created_at": existing_context["created_at"],  # Preserve original creation time
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Recreate the context
    result = await contexts_service.create_context(updated_context, user_id=user.user_id, jwt_token=jwt_token)
    return JSONResponse(result)

async def delete_context(request: Request, contexts_service, session_manager):
    """Delete a context"""
    context_id = request.path_params.get("context_id")
    if not context_id:
        return JSONResponse({"error": "Context ID is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await contexts_service.delete_context(context_id, user_id=user.user_id, jwt_token=jwt_token)
    return JSONResponse(result)