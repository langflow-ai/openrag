"""
Internal file listing and search handlers (cookie auth).

Serves the unversioned internal/UI routes GET /files and GET /files/search
using FileServiceV2 (composite-aggregation cursor pagination). Pass `after_key`
(JSON-encoded) to advance pages.

"""

import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


CREATED_AFTER_DESCRIPTION = (
    "Inclusive lower bound on indexed_time (ISO 8601). "
    "A value with no time is UTC midnight at the start of that day. "
    "Documents with no indexed_time are excluded."
)
CREATED_BEFORE_DESCRIPTION = (
    "Inclusive upper bound on indexed_time (ISO 8601). "
    "A value with no time is UTC midnight at the start of that day, "
    "so pass the next day to include the chosen day. "
    "Documents with no indexed_time are excluded."
)


def _parse_iso_timestamp(value: str, param_name: str) -> datetime:
    """Parse an extended ISO 8601 timestamp, raising HTTP 422 when it is not one."""
    detail = f"{param_name} must be a valid ISO 8601 timestamp"
    if not _EXTENDED_ISO_RE.match(value):
        raise HTTPException(status_code=422, detail=detail)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise HTTPException(status_code=422, detail=detail) from err
    # indexed_time is stored in UTC and OpenSearch reads offset-less values as UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _validate_iso_timestamp(value: str | None, param_name: str) -> None:
    """Raise HTTP 422 when *value* is present but is not a valid ISO 8601 timestamp."""
    if isinstance(value, str):
        _parse_iso_timestamp(value, param_name)


def _validate_date_range(created_after: str | None, created_before: str | None) -> None:
    """Raise HTTP 422 for a malformed bound or a range whose start is after its end."""
    after = (
        _parse_iso_timestamp(created_after, "created_after")
        if isinstance(created_after, str)
        else None
    )
    before = (
        _parse_iso_timestamp(created_before, "created_before")
        if isinstance(created_before, str)
        else None
    )
    if after and before and after > before:
        raise HTTPException(
            status_code=422,
            detail="created_after must be earlier than or equal to created_before",
        )


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
    created_after: str | None = Query(None, description=CREATED_AFTER_DESCRIPTION),
    created_before: str | None = Query(None, description=CREATED_BEFORE_DESCRIPTION),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(get_current_user),
):
    """List ingested files with composite-aggregation pagination, filtering, and sorting."""
    _validate_date_range(created_after, created_before)
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
    created_after: str | None = Query(None, description=CREATED_AFTER_DESCRIPTION),
    created_before: str | None = Query(None, description=CREATED_BEFORE_DESCRIPTION),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(get_current_user),
):
    """Search files by name with fuzzy/partial matching (composite pagination)."""
    _validate_date_range(created_after, created_before)
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
            created_after=created_after,
            created_before=created_before,
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


async def upload_histogram(
    start: str = Query(..., description="Window start (ISO 8601, inclusive)"),
    end: str = Query(..., description="Window end (ISO 8601, inclusive)"),
    tz: str = Query("UTC", description="IANA time zone that defines calendar days"),
    connector_type: list[str] | None = Query(
        None, description="Filter by connector type (repeatable)"
    ),
    mimetype: list[str] | None = Query(None, description="Filter by MIME type (repeatable)"),
    owner: list[str] | None = Query(None, description="Filter by owner (repeatable)"),
    data_sources: list[str] | None = Query(None, description="Filename whitelist (repeatable)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(get_current_user),
):
    """Count distinct uploaded files per calendar day, plus the all-time total."""
    if _parse_iso_timestamp(start, "start") > _parse_iso_timestamp(end, "end"):
        raise HTTPException(status_code=422, detail="start must be earlier than or equal to end")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise HTTPException(status_code=422, detail="tz must be an IANA time zone") from err

    try:
        result = await file_service.upload_histogram(
            user_id=user.user_id,
            jwt_token=user.jwt_token,
            start=start,
            end=end,
            time_zone=tz,
            connector_type=connector_type,
            mimetype=mimetype,
            owner=owner,
            data_sources=data_sources,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("Failed to build upload histogram", error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        return JSONResponse({"error": "Failed to build upload histogram"}, status_code=500)
