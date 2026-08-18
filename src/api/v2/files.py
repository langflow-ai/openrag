"""
Public API v2 Files endpoints (API-key auth).

Cursor-paginated file listing/search over the ingested knowledge base, served
at GET /v2/files and GET /v2/files/search. These handlers delegate to the
internal handlers in api/files.py, overriding only the auth dependency to use
an API key instead of the session cookie.
"""

from fastapi import Depends, Query

from api.files import list_files as _internal_list_files
from api.files import search_files as _internal_search_files
from dependencies import get_file_service_v2, require_api_key_permission
from session_manager import User


async def list_files(
    page: int = Query(
        1, ge=1, description="Page number (for display only; navigation uses after_key cursor)"
    ),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
    connector_type: list[str] | None = Query(
        None, description="Filter by connector type (repeatable)"
    ),
    mimetype: list[str] | None = Query(None, description="Filter by MIME type (repeatable)"),
    owner: list[str] | None = Query(None, description="Filter by owner (repeatable)"),
    search: str | None = Query(None, description="Search filename"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    data_sources: list[str] | None = Query(None, description="Filename whitelist (repeatable)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """List all ingested files (API-key auth). GET /v2/files"""
    return await _internal_list_files(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        search=search,
        after_key=after_key,
        data_sources=data_sources,
        file_service=file_service,
        user=user,
    )


async def search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    connector_type: list[str] | None = Query(
        None, description="Filter by connector type (repeatable)"
    ),
    mimetype: list[str] | None = Query(None, description="Filter by MIME type (repeatable)"),
    owner: list[str] | None = Query(None, description="Filter by owner (repeatable)"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    data_sources: list[str] | None = Query(None, description="Filename whitelist (repeatable)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """Search ingested files by name (API-key auth). GET /v2/files/search"""
    return await _internal_search_files(
        q=q,
        page=page,
        page_size=page_size,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        after_key=after_key,
        data_sources=data_sources,
        file_service=file_service,
        user=user,
    )
