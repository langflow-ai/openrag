import os
from starlette.requests import Request
from starlette.responses import JSONResponse

async def upload(request: Request, document_service, session_manager):
    """Upload a single file"""
    try:
        form = await request.form()
        upload_file = form["file"]
        user = request.state.user
        jwt_token = request.cookies.get("auth_token")
        
        result = await document_service.process_upload_file(upload_file, owner_user_id=user.user_id, jwt_token=jwt_token)
        return JSONResponse(result, status_code=201)  # Created
    except Exception as e:
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)

async def upload_path(request: Request, task_service, session_manager):
    """Upload all files from a directory path"""
    payload = await request.json()
    base_dir = payload.get("path")
    if not base_dir or not os.path.isdir(base_dir):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    file_paths = [os.path.join(root, fn)
                  for root, _, files in os.walk(base_dir)
                  for fn in files]
    
    if not file_paths:
        return JSONResponse({"error": "No files found in directory"}, status_code=400)

    user = request.state.user
    jwt_token = request.cookies.get("auth_token")
    task_id = await task_service.create_upload_task(user.user_id, file_paths, jwt_token=jwt_token)
    
    return JSONResponse({
        "task_id": task_id,
        "total_files": len(file_paths),
        "status": "accepted"
    }, status_code=201)

async def upload_context(request: Request, document_service, chat_service, session_manager):
    """Upload a file and add its content as context to the current conversation"""
    form = await request.form()
    upload_file = form["file"]
    filename = upload_file.filename or "uploaded_document"
    
    # Get optional parameters
    previous_response_id = form.get("previous_response_id")
    endpoint = form.get("endpoint", "langflow")
    
    # Get JWT token from request cookie for authentication
    jwt_token = request.cookies.get("auth_token")
    
    # Get user info from request state (set by auth middleware)
    user = request.state.user
    user_id = user.user_id if user else None

    # Process document and extract content
    doc_result = await document_service.process_upload_context(upload_file, filename)
    
    # Send document content as user message to get proper response_id
    response_text, response_id = await chat_service.upload_context_chat(
        doc_result["content"], 
        filename, 
        user_id=user_id,
        jwt_token=jwt_token,
        previous_response_id=previous_response_id, 
        endpoint=endpoint
    )
    
    response_data = {
        "status": "context_added",
        "filename": doc_result["filename"],
        "pages": doc_result["pages"],
        "content_length": doc_result["content_length"],
        "response_id": response_id,
        "confirmation": response_text
    }
    
    return JSONResponse(response_data)

