"""
Public API v1 Files endpoints.

Provides offset-paginated file listing over the ingested knowledge base
(GET /v1/files/getAll). Uses API-key authentication and calls the shared
FileServiceV2 directly. Cursor-paginated variants live in api/v2/files.py
(list_files_public / search_files_public, served at /v2/files).
"""

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from dependencies import get_file_service, require_api_key_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_all_files(
    limit: int = Query(100, ge=1, le=500, description="Maximum number of files to return"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    search: str | None = Query(None, description="Search filename"),
    file_service=Depends(get_file_service),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """
    Return up to `limit` ingested files using offset-based pagination (page 1).

    GET /v1/files/getAll
    """
    try:
        result = await file_service.list_files(
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            page=1,
            page_size=limit,
            sort_by=sort_by,
            sort_order=sort_order,
            connector_type=connector_type,
            mimetype=mimetype,
            owner=owner,
            search=search,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to get all files (v1)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse({"error": "Failed to get files"}, status_code=500)
