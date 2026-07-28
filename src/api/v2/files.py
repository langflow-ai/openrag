"""
File listing and search API endpoints — v2 (composite aggregation).

Uses composite aggregation for true O(page_size) server-side pagination.
Cursor-based: pass `after_key` (JSON-encoded) to advance pages.
"""

import json

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from dependencies import get_current_user, get_session_manager
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_file_service(session_manager=Depends(get_session_manager)):
    from services.file_service_v2 import FileServiceV2

    return FileServiceV2(session_manager=session_manager)


async def list_files(
    page: int = Query(1, ge=1, description="Page number (for display only; navigation uses after_key cursor)"),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort order"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    search: str | None = Query(None, description="Search filename"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(_get_file_service),
    user: User = Depends(get_current_user),
):
    """List ingested files with composite-aggregation pagination, filtering, and sorting."""
    parsed_after_key: dict | None = None
    if after_key:
        try:
            parsed_after_key = json.loads(after_key)
        except (json.JSONDecodeError, ValueError):
            parsed_after_key = None

    try:
        result = await file_service.list_files(
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            connector_type=connector_type,
            mimetype=mimetype,
            owner=owner,
            search=search,
            after_key=parsed_after_key,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to list files (v2)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse(
            {"error": "Failed to list files", "detail": str(e)},
            status_code=500,
        )


async def search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, description="Items per page"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(_get_file_service),
    user: User = Depends(get_current_user),
):
    """Search files by name with fuzzy/partial matching (v2 — composite pagination)."""
    parsed_after_key: dict | None = None
    if after_key:
        try:
            parsed_after_key = json.loads(after_key)
        except (json.JSONDecodeError, ValueError):
            parsed_after_key = None

    try:
        result = await file_service.search_files(
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            query=q,
            page=page,
            page_size=page_size,
            connector_type=connector_type,
            mimetype=mimetype,
            owner=owner,
            after_key=parsed_after_key,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to search files (v2)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse(
            {"error": "Failed to search files", "detail": str(e)},
            status_code=500,
        )
