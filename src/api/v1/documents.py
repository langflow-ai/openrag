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
from api.v1._filter_resolution import resolve_filter_id
from utils.logging_config import get_logger
from dependencies import (
    get_document_service,
    get_task_service,
    get_session_manager,
    get_langflow_file_service,
    get_knowledge_filter_service,
    get_api_key_user_async,
)
from session_manager import User

logger = get_logger(__name__)


class DeleteDocV1Body(BaseModel):
    filename: Optional[str] = None
    filter_id: Optional[str] = None


async def ingest_endpoint(
    file: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    settings: Optional[str] = Form(None),
    tweaks: Optional[str] = Form(None),
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

    NOTE: `create_filter` is kept here for response-shape compatibility — the
    non-v1 onboarding flow consumes the `create_filter` field echoed back in
    the response. v1 SDK consumers do not currently have a workflow that uses
    it, and the field is never forwarded to the actual ingest task. It should
    be removed in a future major version of the v1 API once we are willing to
    take the breaking change (response no longer contains `create_filter`).
    """
    return await upload_ingest_router(
        file=file,
        session_id=session_id,
        settings_json=settings,
        tweaks_json=tweaks,
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
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    user: User = Depends(get_api_key_user_async),
):
    """Delete document(s) from the knowledge base. DELETE /v1/documents

    Provide exactly one of:
      - `filename`: delete all chunks for that filename.
      - `filter_id`: resolve the filter's `data_sources` and delete chunks for
        each of those filenames. Wildcard (`["*"]`) or empty `data_sources`
        is rejected to prevent mass deletion.
    """
    if bool(body.filename) == bool(body.filter_id):
        return JSONResponse(
            {"error": "Provide exactly one of `filename` or `filter_id`"},
            status_code=400,
        )

    if body.filter_id:
        resolved = await resolve_filter_id(
            body.filter_id,
            knowledge_filter_service,
            user_id=user.user_id,
            jwt_token=None,
        )
        filenames = resolved["filters"].get("data_sources") or []
        if not filenames:
            return JSONResponse(
                {"error": "Filter has no specific data_sources to delete"},
                status_code=400,
            )

        results = []
        total_deleted = 0
        for fname in filenames:
            payload, _status = await delete_documents_by_filename_core(
                filename=fname,
                session_manager=session_manager,
                user_id=user.user_id,
                jwt_token=None,
            )
            results.append(payload)
            total_deleted += payload.get("deleted_chunks", 0) or 0

        return JSONResponse(
            {
                "success": True,
                "deleted_chunks": total_deleted,
                "filenames": filenames,
                "filter_id": body.filter_id,
                "per_file": results,
            }
        )

    payload, status_code = await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=None,
    )
    return JSONResponse(payload, status_code=status_code)
