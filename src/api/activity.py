"""Administrative Activity endpoints: feedback satisfaction.

Access policy (deliberately conservative, feature-local): these endpoints need
an *effective* ``audit:read`` grant. When RBAC enforcement is off, or no-auth
mode is active, the global gates would allow everything, so these endpoints
instead return 403. Operators must enable ``OPENRAG_RBAC_ENFORCE`` to use
Activity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from auth.permission_dependencies import enforce_permission
from dependencies import get_activity_service, get_current_user, get_rbac_service
from session_manager import User

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

NO_STORE = {"Cache-Control": "no-store"}


def activity_access_denied() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"error": "activity_unavailable", "required": "audit:read"},
    )


async def require_activity_admin(
    request: Request,
    user: User = Depends(get_current_user),
    rbac=Depends(get_rbac_service),
) -> User:
    from config.settings import is_no_auth_mode
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced() or is_no_auth_mode():
        raise activity_access_denied()
    return await enforce_permission(request, user, rbac, "audit:read")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _check_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and end <= start:
        raise HTTPException(status_code=422, detail={"error": "invalid_range"})


def serialize_feedback_admin(row: Any, conversation_id: str) -> dict[str, Any]:
    """Admin DTO: no prompt, answer, or source text."""
    return {
        "id": row.id,
        "message_id": row.message_id,
        "conversation_id": conversation_id,
        "user_id": row.user_id,
        "rating": row.rating,
        "comment": row.comment,
        "model_provider": row.model_provider,
        "model": row.model,
        "retrieval": row.retrieval,
        "created_at": _aware(row.created_at).isoformat(),
        "updated_at": _aware(row.updated_at).isoformat(),
    }


async def feedback_list_endpoint(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    rating: Literal["up", "down"] | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None),
    activity_service=Depends(get_activity_service),
    _user: User = Depends(require_activity_admin),
):
    start, end = _aware(start), _aware(end)
    _check_range(start, end)
    page, next_cursor = await activity_service.list_feedback(
        start=start, end=end, rating=rating, limit=limit, cursor=cursor
    )
    return JSONResponse(
        {
            "items": [serialize_feedback_admin(r, c) for r, c in page],
            "next_cursor": next_cursor,
        },
        headers=NO_STORE,
    )


async def feedback_summary_endpoint(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    rating: Literal["up", "down"] | None = Query(default=None),
    activity_service=Depends(get_activity_service),
    _user: User = Depends(require_activity_admin),
):
    start, end = _aware(start), _aware(end)
    _check_range(start, end)
    summary = await activity_service.feedback_summary(start=start, end=end, rating=rating)
    return JSONResponse({**summary, "metric": "feedback_satisfaction"}, headers=NO_STORE)
