from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import INDEX_NAME

logger = get_logger(__name__)


async def check_filename_exists(request: Request, document_service, session_manager):
    """Check if a document with a specific filename already exists"""
    filename = request.query_params.get("filename")

    if not filename:
        return JSONResponse({"error": "filename parameter is required"}, status_code=400)

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    try:
        # Get user's OpenSearch client
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, jwt_token
        )

        # Search for any document with this exact filename
        from utils.opensearch_queries import build_filename_search_body

        search_body = build_filename_search_body(filename, size=1, source=["filename"])

        logger.debug(f"Checking filename existence: {filename}")

        response = await opensearch_client.search(
            index=INDEX_NAME,
            body=search_body
        )

        # Check if any hits were found
        hits = response.get("hits", {}).get("hits", [])
        exists = len(hits) > 0

        logger.debug(f"Filename check result - exists: {exists}, hits: {len(hits)}")

        return JSONResponse({
            "exists": exists,
            "filename": filename
        }, status_code=200)

    except Exception as e:
        logger.error("Error checking filename existence", filename=filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse({"error": "Access denied: insufficient permissions"}, status_code=403)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)


async def delete_documents_by_filename(request: Request, document_service, session_manager):
    """Delete all documents with a specific filename"""
    data = await request.json()
    filename = data.get("filename")

    if not filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    try:
        # Get user's OpenSearch client
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, jwt_token
        )

        # Delete by query to remove all chunks of this document
        from utils.opensearch_queries import build_filename_delete_body

        delete_query = build_filename_delete_body(filename)

        logger.debug(f"Deleting documents with filename: {filename}")

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
            "filename": filename,
            "message": f"All documents with filename '{filename}' deleted successfully"
        }, status_code=200)

    except Exception as e:
        logger.error("Error deleting documents by filename", filename=filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse({"error": "Access denied: insufficient permissions"}, status_code=403)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)
