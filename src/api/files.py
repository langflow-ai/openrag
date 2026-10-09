"""
Internal file listing and search handlers (cookie auth).

Serves the unversioned internal/UI routes GET /files and GET /files/search
using FileServiceV2 (composite-aggregation cursor pagination). Pass `after_key`
(JSON-encoded) to advance pages.

"""

import json
import re
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from dependencies import get_current_user, get_file_service_v2
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

# fromisoformat also accepts basic forms (e.g. "20240101"), which OpenSearch's
# strict_date_optional_time mapping on indexed_time rejects.
_EXTENDED_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?)?"
    r"(Z|[+-]\d{2}:\d{2})?$"
)


def _validate_iso_timestamp(value: str | None, param_name: str) -> None:
    """Raise HTTP 422 when *value* is present but is not a valid ISO 8601 timestamp."""
    if not isinstance(value, str):
        return
    detail = f"{param_name} must be a valid ISO 8601 timestamp"
    if not _EXTENDED_ISO_RE.match(value):
        raise HTTPException(status_code=422, detail=detail)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise HTTPException(status_code=422, detail=detail) from err


def _parse_after_key(after_key: str | None) -> dict | None:
    """Parse a JSON-encoded composite cursor.

    Returns None when after_key is absent.
    Raises HTTPException 400 when the value is present but is not valid JSON
    or does not decode to a dict (e.g. a bare string or number is invalid).
    """
    if not after_key:
        return None
    try:
        parsed = json.loads(after_key)
    except (json.JSONDecodeError, ValueError) as err:
        raise HTTPException(status_code=400, detail="after_key is not valid JSON") from err
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="after_key must be a JSON object")
    return parsed


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
    created_after: str | None = Query(None, description="Filter files created after ISO timestamp"),
    created_before: str | None = Query(
        None, description="Filter files created before ISO timestamp"
    ),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(get_current_user),
):
    """List ingested files with composite-aggregation pagination, filtering, and sorting."""
    _validate_iso_timestamp(created_after, "created_after")
    _validate_iso_timestamp(created_before, "created_before")
    parsed_after_key = _parse_after_key(after_key)

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
            data_sources=data_sources,
            created_after=created_after,
            created_before=created_before,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to list files (v2)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse(
            {"error": "Failed to list files"},
            status_code=500,
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
    user: User = Depends(get_current_user),
):
    """Search files by name with fuzzy/partial matching (composite pagination)."""
    parsed_after_key = _parse_after_key(after_key)

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
            data_sources=data_sources,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to search files (v2)", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse(
            {"error": "Failed to search files"},
            status_code=500,
        )
