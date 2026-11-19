"""Read-side Activity policy: filtering, pagination and summaries.

Route handlers delegate here so that session lifecycle, cursor binding and the
frozen upper time bound live in one injected service rather than in the HTTP
layer. Authorization stays in the route dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from db.repositories import FeedbackRepo
from services.activity_cursor import decode_cursor, encode_cursor


def feedback_filters(
    start: datetime | None, end: datetime | None, rating: str | None
) -> dict[str, Any]:
    return {
        "k": "feedback",
        "s": start.isoformat() if start else None,
        "e": end.isoformat() if end else None,
        "r": rating,
    }


def bounded_end(end: datetime | None, cursor_upper: datetime | None) -> datetime:
    """Freeze an exclusive upper bound so later inserts never shift paging."""
    frozen = cursor_upper or datetime.now(UTC) + timedelta(microseconds=1)
    return min(frozen, end) if end is not None else frozen


class ActivityService:
    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from db.engine import SessionLocal, init_engine

        if SessionLocal is None:
            init_engine()
        from db.engine import SessionLocal as factory

        assert factory is not None
        return factory()

    async def list_feedback(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        rating: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[tuple[Any, str]], str | None]:
        """Return one page of ``(feedback, conversation_id)`` and the next cursor."""
        filters = feedback_filters(start, end, rating)
        decoded = decode_cursor(cursor, filters) if cursor else None
        upper = bounded_end(end, decoded.upper if decoded else None)
        async with self._session() as session:
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
        return page, next_cursor

    async def feedback_summary(
        self, *, start: datetime | None, end: datetime | None, rating: str | None
    ) -> dict[str, Any]:
        async with self._session() as session:
            return await FeedbackRepo(session).summary(start=start, end=end, rating=rating)
