import os
from starlette.requests import Request
from starlette.responses import JSONResponse

async def upload(request: Request, document_service, session_manager):
    """Upload a single file"""
    form = await request.form()
    upload_file = form["file"]
    user = request.state.user
    
    result = await document_service.process_upload_file(upload_file, owner_user_id=user.user_id)
    return JSONResponse(result)

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
    task_id = await task_service.create_upload_task(user.user_id, file_paths)
    
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

    # Process document and extract content
    doc_result = await document_service.process_upload_context(upload_file, filename)
    
    # Send document content as user message to get proper response_id
    response_text, response_id = await chat_service.upload_context_chat(
        doc_result["content"], 
        filename, 
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

async def task_status(request: Request, task_service, session_manager):
    """Get the status of an upload task"""
    task_id = request.path_params.get("task_id")
    user = request.state.user
    
    task_status_result = task_service.get_task_status(user.user_id, task_id)
    if not task_status_result:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    
    return JSONResponse(task_status_result)