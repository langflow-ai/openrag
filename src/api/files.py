"""
File listing and search API endpoints.

Provides server-side file-level views over the chunk-based OpenSearch index,
replacing the client-side chunk-to-file aggregation pattern.
"""

from typing import Optional

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from dependencies import get_session_manager, get_current_user
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_file_service(session_manager=Depends(get_session_manager)):
    from services.file_service import FileService
    return FileService(session_manager=session_manager)


async def list_files(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort order"),
    connector_type: Optional[str] = Query(None, description="Filter by connector type"),
    mimetype: Optional[str] = Query(None, description="Filter by MIME type"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
    search: Optional[str] = Query(None, description="Search filename"),
    file_service=Depends(_get_file_service),
    user: User = Depends(get_current_user),
):
    """List ingested files with pagination, filtering, and sorting."""
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
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to list files", error=str(e))
        return JSONResponse(
            {"error": "Failed to list files", "detail": str(e)},
            status_code=500,
        )


async def search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    connector_type: Optional[str] = Query(None, description="Filter by connector type"),
    mimetype: Optional[str] = Query(None, description="Filter by MIME type"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
    file_service=Depends(_get_file_service),
    user: User = Depends(get_current_user),
):
    """Search files by name with fuzzy/partial matching."""
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
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to search files", error=str(e))
        return JSONResponse(
            {"error": "Failed to search files", "detail": str(e)},
            status_code=500,
        )
