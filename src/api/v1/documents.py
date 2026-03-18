"""
Public API v1 Documents endpoint.

Provides document ingestion and management.
Uses API key authentication.
"""
from typing import List, Optional

from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from api.documents import delete_documents_by_filename_core

from api.router import upload_ingest_router
from utils.logging_config import get_logger
from dependencies import (
    get_document_service,
    get_task_service,
    get_session_manager,
    get_langflow_file_service,
    get_api_key_user_async,
)
from session_manager import User

logger = get_logger(__name__)


class DeleteDocV1Body(BaseModel):
    filename: str


async def ingest_endpoint(
    file: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    settings: Optional[str] = Form(None),
    tweaks: Optional[str] = Form(None),
    delete_after_ingest: str = Form("true"),
    replace_duplicates: str = Form("true"),
    create_filter: str = Form("false"),
    document_service=Depends(get_document_service),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    user: User = Depends(get_api_key_user_async),
):
    """
    Ingest a document into the knowledge base.

    POST /v1/documents/ingest
    Request: multipart/form-data with "file" field
    """
    # Delegate to the router which handles both Langflow and traditional paths
    return await upload_ingest_router(
        file=file,
        session_id=session_id,
        settings_json=settings,
        tweaks_json=tweaks,
        delete_after_ingest=delete_after_ingest,
        replace_duplicates=replace_duplicates,
        create_filter=create_filter,
        document_service=document_service,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        task_service=task_service,
        user=user,
    )


async def task_status_endpoint(
    task_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(get_api_key_user_async),
):
    """Get the status of an ingestion task. GET /v1/tasks/{task_id}"""
    task_status = task_service.get_task_status(user.user_id, task_id)
    if not task_status:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(task_status)


async def delete_document_endpoint(
    body: DeleteDocV1Body,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """Delete a document from the knowledge base. DELETE /v1/documents"""
    payload, status_code = await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=None,
    )
    return JSONResponse(payload, status_code=status_code)
