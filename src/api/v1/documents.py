"""
Public API v1 Documents endpoint.

Provides document ingestion and management.
Uses API key authentication.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def ingest_endpoint(request: Request, document_service, task_service, session_manager):
    """
    Ingest a document into the knowledge base.

    POST /api/v1/documents/ingest

    Request: multipart/form-data with "file" field

    Response:
        {
            "success": true,
            "document_id": "...",
            "filename": "doc.pdf",
            "chunks": 10
        }

    For bulk uploads, returns a task ID:
        {
            "task_id": "...",
            "status": "processing"
        }
    """
    try:
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            # Single file upload
            form = await request.form()
            upload_file = form.get("file")

            if not upload_file:
                return JSONResponse(
                    {"error": "File is required"},
                    status_code=400,
                )

            user = request.state.user

            result = await document_service.process_upload_file(
                upload_file,
                owner_user_id=user.user_id,
                jwt_token=None,  # API key auth, no JWT
                owner_name=user.name,
                owner_email=user.email,
            )

            if result.get("error"):
                return JSONResponse(result, status_code=500)

            return JSONResponse({
                "success": True,
                "document_id": result.get("id"),  # process_upload_file returns "id"
                "filename": upload_file.filename,
                "chunks": result.get("chunks", 0),
            }, status_code=201)

        else:
            return JSONResponse(
                {"error": "Content-Type must be multipart/form-data"},
                status_code=400,
            )

    except Exception as e:
        error_msg = str(e)
        logger.error("Document ingestion failed", error=error_msg)

        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        else:
            return JSONResponse({"error": error_msg}, status_code=500)


async def delete_document_endpoint(request: Request, document_service, session_manager):
    """
    Delete a document from the knowledge base.

    DELETE /api/v1/documents

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
