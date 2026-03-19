from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


class DeleteDocumentBody(BaseModel):
    filename: str


async def delete_documents_by_filename_core(
    filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
):
    """Shared delete-by-filename logic for v1 and non-v1 endpoints."""
    from config.settings import get_index_name
    from utils.opensearch_queries import build_filename_delete_body

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
        opensearch_client = session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )
        delete_query = build_filename_delete_body(normalized_filename)
        result = await opensearch_client.delete_by_query(
            index=get_index_name(),
            body=delete_query,
            conflicts="proceed",
        )

        deleted_count = result.get("deleted", 0)
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


async def _ensure_index_exists():
    """Create the OpenSearch index if it doesn't exist yet."""
    from main import init_index
    await init_index()


async def check_filename_exists(
    filename: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Check if a document with a specific filename already exists"""
    from config.settings import get_index_name

    jwt_token = user.jwt_token

    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, jwt_token
        )

        from utils.opensearch_queries import build_filename_search_body

        search_body = build_filename_search_body(filename, size=1, source=["filename"])

        logger.debug("Checking filename existence", filename=filename, index_name=get_index_name())

        try:
            response = await opensearch_client.search(
                index=get_index_name(),
                body=search_body
            )
        except Exception as search_err:
            if "index_not_found_exception" in str(search_err):
                logger.info("Index does not exist, creating it now before upload")
                await _ensure_index_exists()
                return JSONResponse({"exists": False, "filename": filename}, status_code=200)
            raise

        hits = response.get("hits", {}).get("hits", [])
        exists = len(hits) > 0

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
    )
    return JSONResponse(payload, status_code=status_code)
