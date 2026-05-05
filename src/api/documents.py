from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_session_manager, get_current_user
from session_manager import User
from services.knowledge_access import build_access_context
from services.knowledge_backend import get_knowledge_backend_service

logger = get_logger(__name__)


class DeleteDocumentBody(BaseModel):
    filename: str


async def delete_documents_by_filename_core(
    filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
    user_email: str | None = None,
):
    """Shared delete-by-filename logic for v1 and non-v1 endpoints."""

    normalized_filename = (filename or "").strip()
    if not normalized_filename:
        return (
            {
                "success": False,
                "deleted_chunks": 0,
                "filename": normalized_filename,
                "message": None,
                "error": "Filename is required",
            },
            400,
        )

    try:
        access_context = build_access_context(
            user_id=user_id,
            user_email=user_email,
            jwt_token=jwt_token,
            session_manager=session_manager,
        )
        knowledge_backend = get_knowledge_backend_service(session_manager)
        deleted_count = await knowledge_backend.delete_by_filename(
            normalized_filename,
            access_context,
        )
        logger.info(
            f"Deleted {deleted_count} chunks for filename {normalized_filename}",
            user_id=user_id,
        )

        if deleted_count == 0:
            return (
                {
                    "success": False,
                    "deleted_chunks": 0,
                    "filename": normalized_filename,
                    "message": None,
                    "error": "No matching document chunks were deleted. The file may be missing or not deletable in the current user context.",
                },
                404,
            )

        return (
            {
                "success": True,
                "deleted_chunks": deleted_count,
                "filename": normalized_filename,
                "message": f"All documents with filename '{normalized_filename}' deleted successfully",
                "error": None,
            },
            200,
        )
    except Exception as e:
        logger.error(
            "Error deleting documents by filename",
            filename=normalized_filename,
            error=str(e),
        )
        error_str = str(e)
        status_code = 403 if "AuthenticationException" in error_str else 500
        return (
            {
                "success": False,
                "deleted_chunks": 0,
                "filename": normalized_filename,
                "message": None,
                "error": (
                    "Access denied: insufficient permissions"
                    if status_code == 403
                    else "An internal error has occurred while deleting documents"
                ),
            },
            status_code,
        )


async def _ensure_index_exists(jwt_token: str = None):
    """Create the OpenSearch index if it doesn't exist yet."""
    from main import init_index
    from config.settings import (
        IBM_AUTH_ENABLED,
        clients as app_clients,
        get_knowledge_backend,
    )

    if get_knowledge_backend() != "opensearch":
        return

    opensearch_client = None
    if IBM_AUTH_ENABLED and jwt_token:
        opensearch_client = app_clients.create_user_opensearch_client(jwt_token)

    await init_index(opensearch_client)


async def check_filename_exists(
    filename: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Check if a document with a specific filename already exists"""
    jwt_token = user.jwt_token

    try:
        access_context = build_access_context(
            user_id=user.user_id,
            user_email=user.email,
            jwt_token=jwt_token,
            session_manager=session_manager,
        )
        knowledge_backend = get_knowledge_backend_service(session_manager)

        try:
            exists = await knowledge_backend.filename_exists(filename, access_context)
        except Exception as search_err:
            if "index_not_found_exception" in str(search_err):
                logger.info("Index does not exist, creating it now before upload")
                await _ensure_index_exists(jwt_token)
                return JSONResponse({"exists": False, "filename": filename}, status_code=200)
            raise

        return JSONResponse({"exists": exists, "filename": filename}, status_code=200)

    except Exception as e:
        logger.error("Error checking filename existence", filename=filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse({"error": "Access denied: insufficient permissions"}, status_code=403)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)


async def delete_documents_by_filename(
    body: DeleteDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
    ):
    """Delete all documents with a specific filename"""
    payload, status_code =await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=user.jwt_token,
        user_email=user.email,
    )
    return JSONResponse(payload, status_code=status_code)
