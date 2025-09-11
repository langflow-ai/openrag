import os
from urllib.parse import urlparse
import boto3
from starlette.requests import Request
from starlette.responses import JSONResponse
from .upload_utils import extract_user_context


async def upload_path(request: Request, task_service, session_manager, langflow_file_service):
    """Upload all files from a directory path"""
    payload = await request.json()
    base_dir = payload.get("path")
    if not base_dir or not os.path.isdir(base_dir):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    file_paths = [
        os.path.join(root, fn) for root, _, files in os.walk(base_dir) for fn in files
    ]

    if not file_paths:
        return JSONResponse({"error": "No files found in directory"}, status_code=400)

    ctx = await extract_user_context(request)
    owner_user_id = ctx["owner_user_id"]
    owner_name = ctx["owner_name"]
    owner_email = ctx["owner_email"]
    jwt_token = ctx["jwt_token"]

    from config.settings import DISABLE_INGEST_WITH_LANGFLOW
    
    # Use same logic as single file uploads - respect the Langflow setting
    if DISABLE_INGEST_WITH_LANGFLOW:
        # Use direct DocumentFileProcessor (no Langflow)
        task_id = await task_service.create_upload_task(
            owner_user_id,
            file_paths,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )
    else:
        # Use Langflow pipeline for processing
        task_id = await task_service.create_langflow_upload_task(
            user_id=owner_user_id,
            file_paths=file_paths,
            langflow_file_service=langflow_file_service,
            session_manager=session_manager,
            jwt_token=jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )

    return JSONResponse(
        {"task_id": task_id, "total_files": len(file_paths), "status": "accepted"},
        status_code=201,
    )


async def upload_context(
    request: Request, document_service, chat_service, session_manager
):
    """Upload a file and add its content as context to the current conversation"""
    form = await request.form()
    upload_file = form["file"]
    filename = upload_file.filename or "uploaded_document"

    # Get optional parameters
    previous_response_id = form.get("previous_response_id")
    endpoint = form.get("endpoint", "langflow")

    # Get JWT token from auth middleware
    jwt_token = request.state.jwt_token

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
        endpoint=endpoint,
    )

    response_data = {
        "status": "context_added",
        "filename": doc_result["filename"],
        "pages": doc_result["pages"],
        "content_length": doc_result["content_length"],
        "response_id": response_id,
        "confirmation": response_text,
    }

    return JSONResponse(response_data)


async def upload_options(request: Request, session_manager):
    """Return availability of upload features"""
    aws_enabled = bool(
        os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    return JSONResponse({"aws": aws_enabled})


async def upload_bucket(request: Request, task_service, session_manager):
    """Process all files from an S3 bucket URL"""
    if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
        return JSONResponse(
            {"error": "AWS credentials not configured"}, status_code=400
        )

    payload = await request.json()
    s3_url = payload.get("s3_url")
    if not s3_url or not s3_url.startswith("s3://"):
        return JSONResponse({"error": "Invalid S3 URL"}, status_code=400)

    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")

    s3_client = boto3.client("s3")
    keys = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("/"):
                keys.append(key)

    if not keys:
        return JSONResponse({"error": "No files found in bucket"}, status_code=400)

    from models.processors import S3FileProcessor
    from .upload_utils import extract_user_context

    ctx = await extract_user_context(request)
    owner_user_id = ctx["owner_user_id"]
    owner_name = ctx["owner_name"]
    owner_email = ctx["owner_email"]
    jwt_token = ctx["jwt_token"]
    task_user_id = owner_user_id

    processor = S3FileProcessor(
        task_service.document_service,
        bucket,
        s3_client=s3_client,
        owner_user_id=owner_user_id,
        jwt_token=jwt_token,
        owner_name=owner_name,
        owner_email=owner_email,
    )

    task_id = await task_service.create_custom_task(task_user_id, keys, processor)

    return JSONResponse(
        {"task_id": task_id, "total_files": len(keys), "status": "accepted"},
        status_code=201,
    )
