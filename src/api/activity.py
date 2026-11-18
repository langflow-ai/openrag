"""Administrative Activity endpoints: feedback satisfaction.

Access policy (deliberately conservative, feature-local): these endpoints need
an *effective* ``audit:read`` grant. When RBAC enforcement is off, or no-auth
mode is active, the global gates would allow everything, so these endpoints
instead return 403. Operators must enable ``OPENRAG_RBAC_ENFORCE`` to use
Activity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from auth.permission_dependencies import enforce_permission
from db.repositories import FeedbackRepo
from dependencies import get_current_user, get_rbac_service
from services.activity_cursor import decode_cursor, encode_cursor
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


def _session():
    from db.engine import SessionLocal, init_engine

    if SessionLocal is None:
        init_engine()
    from db.engine import SessionLocal as factory

    assert factory is not None
    return factory()


def _feedback_filters(start, end, rating) -> dict:
    return {
        "k": "feedback",
        "s": start.isoformat() if start else None,
        "e": end.isoformat() if end else None,
        "r": rating,
    }


def _bounded_end(end: datetime | None, cursor_upper: datetime | None) -> datetime:
    """Freeze an exclusive upper bound so later inserts never shift paging."""
    frozen = cursor_upper or datetime.now(UTC) + timedelta(microseconds=1)
    return min(frozen, end) if end is not None else frozen


async def feedback_list_endpoint(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    rating: Literal["up", "down"] | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None),
    _user: User = Depends(require_activity_admin),
):
    start, end = _aware(start), _aware(end)
    _check_range(start, end)
    filters = _feedback_filters(start, end, rating)
    decoded = decode_cursor(cursor, filters) if cursor else None
    upper = _bounded_end(end, decoded.upper if decoded else None)
    async with _session() as session:
        rows = await FeedbackRepo(session).list_page(
            start=start,
            end=upper,
            rating=rating,
            limit=limit + 1,
            after=(decoded.ts, decoded.id) if decoded else None,
        )
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id, upper, filters)
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
    _user: User = Depends(require_activity_admin),
):
    start, end = _aware(start), _aware(end)
    _check_range(start, end)
    async with _session() as session:
        summary = await FeedbackRepo(session).summary(start=start, end=end, rating=rating)
    return JSONResponse(
        {**summary, "metric": "feedback_satisfaction"},
        headers=NO_STORE,
    )
