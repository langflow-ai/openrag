import os
from typing import Optional
from urllib.parse import urlparse

import boto3
from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from dependencies import (
    get_document_service,
    get_task_service,
    get_chat_service,
    get_session_manager,
    get_current_user,
)
from session_manager import User


class UploadPathBody(BaseModel):
    path: str


class UploadBucketBody(BaseModel):
    s3_url: str


async def upload(
    file: UploadFile = File(...),
    document_service=Depends(get_document_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload a single file"""
    try:

        from config.settings import is_no_auth_mode

        if is_no_auth_mode():
            owner_user_id = None
            owner_name = None
            owner_email = None
        else:
            owner_user_id = user.user_id
            owner_name = user.name
            owner_email = user.email

        result = await document_service.process_upload_file(
            file,
            owner_user_id=owner_user_id,
            jwt_token=user.jwt_token,
            owner_name=owner_name,
            owner_email=owner_email,
        )
        return JSONResponse(result, status_code=201)
    except Exception as e:
        error_msg = str(e)
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)


async def upload_path(
    body: UploadPathBody,
    task_service=Depends(get_task_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload all files from a directory path"""
    if not body.path or not os.path.isdir(body.path):
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    file_paths = [
        os.path.join(root, fn) for root, _, files in os.walk(body.path) for fn in files
    ]

    if not file_paths:
        return JSONResponse({"error": "No files found in directory"}, status_code=400)

    jwt_token = user.jwt_token

    from config.settings import is_no_auth_mode

    if is_no_auth_mode():
        owner_user_id = None
        owner_name = None
        owner_email = None
    else:
        owner_user_id = user.user_id
        owner_name = user.name
        owner_email = user.email

    from api.documents import _ensure_index_exists
    await _ensure_index_exists()

    task_id = await task_service.create_upload_task(
        owner_user_id,
        file_paths,
        jwt_token=jwt_token,
        owner_name=owner_name,
        owner_email=owner_email,
    )

    return JSONResponse(
        {"task_id": task_id, "total_files": len(file_paths), "status": "accepted"},
        status_code=201,
    )


async def upload_context(
    file: UploadFile = File(...),
    previous_response_id: Optional[str] = Form(None),
    endpoint: str = Form("langflow"),
    document_service=Depends(get_document_service),
    chat_service=Depends(get_chat_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Upload a file and add its content as context to the current conversation"""
    filename = file.filename or "uploaded_document"
    user_id = user.user_id if user else None

    jwt_token = user.jwt_token

    doc_result = await document_service.process_upload_context(file, filename)

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


async def upload_options(
    user: User = Depends(get_current_user),
):
    """Return availability of upload features"""
    aws_enabled = bool(
        os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    from config.settings import UPLOAD_BATCH_SIZE
    return JSONResponse({"aws": aws_enabled, "upload_batch_size": UPLOAD_BATCH_SIZE})


async def upload_bucket(
    body: UploadBucketBody,
    task_service=Depends(get_task_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Process all files from an S3 bucket URL"""
    if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
        return JSONResponse(
            {"error": "AWS credentials not configured"}, status_code=400
        )

    if not body.s3_url or not body.s3_url.startswith("s3://"):
        return JSONResponse({"error": "Invalid S3 URL"}, status_code=400)

    parsed = urlparse(body.s3_url)
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

    jwt_token = user.jwt_token

    from models.processors import S3FileProcessor
    from config.settings import is_no_auth_mode

    if is_no_auth_mode():
        owner_user_id = None
        owner_name = None
        owner_email = None
        task_user_id = None
    else:
        owner_user_id = user.user_id
        owner_name = user.name
        owner_email = user.email
        task_user_id = user.user_id

    from api.documents import _ensure_index_exists
    await _ensure_index_exists()

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
