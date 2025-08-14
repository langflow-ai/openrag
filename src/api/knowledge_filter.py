from starlette.requests import Request
from starlette.responses import JSONResponse
import uuid
from datetime import datetime

async def create_knowledge_filter(request: Request, knowledge_filter_service, session_manager):
    """Create a new knowledge filter"""
    payload = await request.json()
    
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "Knowledge filter name is required"}, status_code=400)
    
    description = payload.get("description", "")
    query_data = payload.get("queryData")
    if not query_data:
        return JSONResponse({"error": "Query data is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    # Create knowledge filter document
    filter_id = str(uuid.uuid4())
    filter_doc = {
        "id": filter_id,
        "name": name,
        "description": description,
        "query_data": query_data,  # Store the full search query JSON
        "owner": user.user_id,
        "allowed_users": payload.get("allowedUsers", []),  # ACL field for future use
        "allowed_groups": payload.get("allowedGroups", []),  # ACL field for future use
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    result = await knowledge_filter_service.create_knowledge_filter(filter_doc, user_id=user.user_id, jwt_token=jwt_token)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=201)  # Created
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)

async def search_knowledge_filters(request: Request, knowledge_filter_service, session_manager):
    """Search for knowledge filters by name, description, or query content"""
    payload = await request.json()
    
    query = payload.get("query", "")
    limit = payload.get("limit", 20)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await knowledge_filter_service.search_knowledge_filters(query, user_id=user.user_id, jwt_token=jwt_token, limit=limit)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)

async def get_knowledge_filter(request: Request, knowledge_filter_service, session_manager):
    """Get a specific knowledge filter by ID"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse({"error": "Knowledge filter ID is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await knowledge_filter_service.get_knowledge_filter(filter_id, user_id=user.user_id, jwt_token=jwt_token)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)

async def update_knowledge_filter(request: Request, knowledge_filter_service, session_manager):
    """Update an existing knowledge filter by delete + recreate (due to DLS limitations)"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse({"error": "Knowledge filter ID is required"}, status_code=400)
    
    payload = await request.json()
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    # First, get the existing knowledge filter
    existing_result = await knowledge_filter_service.get_knowledge_filter(filter_id, user_id=user.user_id, jwt_token=jwt_token)
    if not existing_result.get("success"):
        return JSONResponse({"error": "Knowledge filter not found or access denied"}, status_code=404)
    
    existing_filter = existing_result["filter"]
    
    # Delete the existing knowledge filter
    delete_result = await knowledge_filter_service.delete_knowledge_filter(filter_id, user_id=user.user_id, jwt_token=jwt_token)
    if not delete_result.get("success"):
        return JSONResponse({"error": "Failed to delete existing knowledge filter"}, status_code=500)
    
    # Create updated knowledge filter document with same ID
    updated_filter = {
        "id": filter_id,
        "name": payload.get("name", existing_filter["name"]),
        "description": payload.get("description", existing_filter["description"]),
        "query_data": payload.get("queryData", existing_filter["query_data"]),
        "owner": existing_filter["owner"],
        "allowed_users": payload.get("allowedUsers", existing_filter.get("allowed_users", [])),
        "allowed_groups": payload.get("allowedGroups", existing_filter.get("allowed_groups", [])),
        "created_at": existing_filter["created_at"],  # Preserve original creation time
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Recreate the knowledge filter
    result = await knowledge_filter_service.create_knowledge_filter(updated_filter, user_id=user.user_id, jwt_token=jwt_token)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)  # Updated successfully
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)

async def delete_knowledge_filter(request: Request, knowledge_filter_service, session_manager):
    """Delete a knowledge filter"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse({"error": "Knowledge filter ID is required"}, status_code=400)
    
    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    
    result = await knowledge_filter_service.delete_knowledge_filter(filter_id, user_id=user.user_id, jwt_token=jwt_token)
    
    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower() or "already deleted" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif "access denied" in error_msg.lower() or "insufficient permissions" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)