"""
Public API v1 Documents endpoint.

Provides document ingestion and management.
Uses API key authentication.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.router import upload_ingest_router
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def ingest_endpoint(
    request: Request,
    document_service,
    task_service,
    session_manager,
    langflow_file_service,
):
    """
    Ingest a document into the knowledge base.

    POST /v1/documents/ingest

    Request: multipart/form-data with "file" field

    Response (async via Langflow):
        {
            "task_id": "...",
            "status": "processing",
            "filename": "doc.pdf"
        }

    Response (sync when Langflow disabled):
        {
            "success": true,
            "document_id": "...",
            "filename": "doc.pdf",
            "chunks": 10
        }
    """
    # Delegate to the existing upload_ingest_router which handles both
    # Langflow and traditional paths
    return await upload_ingest_router(
        request,
        document_service=document_service,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        task_service=task_service,
    )


async def task_status_endpoint(request: Request, task_service, session_manager):
    """
    Get the status of an ingestion task.

    GET /v1/tasks/{task_id}

    Response:
        {
            "task_id": "...",
            "status": "completed",
            "total_files": 1,
            "processed_files": 1,
            "successful_files": 1,
            "failed_files": 0,
            "files": {...}
        }
    """
    task_id = request.path_params.get("task_id")
    user = request.state.user

    task_status = task_service.get_task_status(user.user_id, task_id)
    if not task_status:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return JSONResponse(task_status)


async def delete_document_endpoint(request: Request, document_service, session_manager):
    """
    Delete a document from the knowledge base.

    DELETE /v1/documents

    Request body:
        {
            "filename": "doc.pdf"
        }

    Response:
        {
            "success": true,
            "deleted_chunks": 5
        }
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    filename = data.get("filename", "").strip()
    if not filename:
        return JSONResponse(
            {"error": "Filename is required"},
            status_code=400,
        )

    user = request.state.user

    try:
        from config.settings import INDEX_NAME
        from utils.opensearch_queries import build_filename_delete_body

        # Get OpenSearch client (API key auth uses internal client)
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, None  # No JWT for API key auth
        )

        # Delete by query to remove all chunks of this document
        delete_query = build_filename_delete_body(filename)

        result = await opensearch_client.delete_by_query(
            index=INDEX_NAME,
            body=delete_query,
            conflicts="proceed"
        )

        deleted_count = result.get("deleted", 0)
        logger.info(f"Deleted {deleted_count} chunks for filename {filename}", user_id=user.user_id)

        return JSONResponse({
            "success": True,
            "deleted_chunks": deleted_count,
        })

    except Exception as e:
        error_msg = str(e)
        logger.error("Document deletion failed", error=error_msg, filename=filename)

        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)
