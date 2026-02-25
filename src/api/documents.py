from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


class DeleteDocumentBody(BaseModel):
    filename: str


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
    from config.settings import get_index_name

    jwt_token = user.jwt_token

    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, jwt_token
        )

        from utils.opensearch_queries import build_filename_delete_body

        delete_query = build_filename_delete_body(body.filename)

        logger.debug(f"Deleting documents with filename: {body.filename}")

        result = await opensearch_client.delete_by_query(
            index=get_index_name(),
            body=delete_query,
            conflicts="proceed"
        )

        deleted_count = result.get("deleted", 0)
        logger.info(f"Deleted {deleted_count} chunks for filename {body.filename}", user_id=user.user_id)

        return JSONResponse({
            "success": True,
            "deleted_chunks": deleted_count,
            "filename": body.filename,
            "message": f"All documents with filename '{body.filename}' deleted successfully"
        }, status_code=200)

    except Exception as e:
        logger.error("Error deleting documents by filename", filename=body.filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse({"error": "Access denied: insufficient permissions"}, status_code=403)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)
