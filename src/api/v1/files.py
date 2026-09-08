"""
Public API v1 Files endpoints.

Provides a simple file listing over the ingested knowledge base
(GET /v1/files/get_all). Uses API-key authentication and calls FileService
(v1, offset pagination) directly.
"""

from fastapi import Depends
from fastapi.responses import JSONResponse

from dependencies import get_file_service, require_api_key_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_all_files(
    file_service=Depends(get_file_service),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """
    Return all ingested files.

    GET /v1/files/get_all
    """
    try:
        result = await file_service.list_files(
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            page=1,
            page_size=500,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to get all files (v1)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse({"error": "Failed to get files"}, status_code=500)
