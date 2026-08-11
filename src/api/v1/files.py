"""
Public API v1 Files endpoints.

Provides file listing and search over the ingested knowledge base.
Uses API key authentication — delegates to the api/v2/files.py handlers
but overrides the user dependency to use API keys.
"""

from fastapi import Depends, Query

from api.v2 import files as files_v2
from dependencies import get_file_service_v2, require_api_key_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def list_files(
    page: int = Query(
        1, ge=1, description="Page number (for display only; navigation uses after_key cursor)"
    ),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    search: str | None = Query(None, description="Search filename"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """
    List all ingested files.

    GET /v1/files
    """
    return await files_v2.list_files(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        search=search,
        after_key=after_key,
        file_service=file_service,
        user=user,
    )


async def search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """
    Search ingested files by name with fuzzy/partial matching.

    GET /v1/files/search
    """
    return await files_v2.search_files(
        q=q,
        page=page,
        page_size=page_size,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        after_key=after_key,
        file_service=file_service,
        user=user,
    )
