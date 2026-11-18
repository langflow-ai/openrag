"""Persistence for answer feedback (see ``db.models.message_feedback``)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import ChatConversation, ChatMessage, MessageFeedback


def _upsert_insert(session: AsyncSession):
    """Return the dialect's INSERT supporting ON CONFLICT (SQLite and Postgres)."""
    name = session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover - only the two supported databases
        raise RuntimeError(f"Feedback upsert is unsupported on dialect {name!r}")
    return insert


def naive_utc(value: datetime) -> datetime:
    """Normalise to aware UTC (the ORM column type requires tz-aware values).

    Name kept for the audit repo import; storage is UTC either way.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class FeedbackRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: str, message_id: str) -> MessageFeedback | None:
        result = await self.session.execute(
            select(MessageFeedback).where(
                col(MessageFeedback.user_id) == user_id,
                col(MessageFeedback.message_id) == message_id,
            )
        )
        return result.scalar_one_or_none()

    async def for_user_messages(
        self, user_id: str, message_ids: list[str]
    ) -> dict[str, MessageFeedback]:
        """Return the caller's own feedback keyed by message id."""
        if not message_ids:
            return {}
        found: dict[str, MessageFeedback] = {}
        # Chunk to stay under SQLite's bound-parameter limit.
        for start in range(0, len(message_ids), 500):
            result = await self.session.execute(
                select(MessageFeedback).where(
                    col(MessageFeedback.user_id) == user_id,
                    col(MessageFeedback.message_id).in_(message_ids[start : start + 500]),
                )
            )
            for row in result.scalars().all():
                found[row.message_id] = row
        return found

    async def upsert(
        self,
        *,
        user_id: str,
        message_id: str,
        rating: str,
        comment: str | None,
        model_provider: str | None,
        model: str | None,
        retrieval: dict[str, Any] | None,
    ) -> MessageFeedback:
        """Atomically create or replace one user's feedback for a message.

        ``created_at`` is preserved; ``updated_at`` only advances when the
        rating or comment really changes, so an identical resubmission is a
        no-op. Provenance is copied once at creation and never rewritten.
        """
        now = naive_utc(datetime.now(UTC))
        stmt = _upsert_insert(self.session)(MessageFeedback).values(
            id=uuid4().hex,
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
            model_provider=model_provider,
            model=model,
            retrieval=retrieval,
            created_at=now,
            updated_at=now,
        )
        table = MessageFeedback.__table__  # type: ignore[attr-defined]
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "message_id"],
            set_={
                "rating": stmt.excluded.rating,
                "comment": stmt.excluded.comment,
                "updated_at": now,
            },
            where=or_(
                table.c.rating != stmt.excluded.rating,
                table.c.comment.is_distinct_from(stmt.excluded.comment),
            ),
        )
        await self.session.execute(stmt)
        row = await self.get(user_id, message_id)
        assert row is not None
        await self.session.refresh(row)
        return row

    # --- administrative reads -------------------------------------------------

    @staticmethod
    def _filters(*, start: datetime | None, end: datetime | None, rating: str | None) -> list[Any]:
        clauses: list[Any] = []
        if start is not None:
            clauses.append(col(MessageFeedback.created_at) >= naive_utc(start))
        if end is not None:
            clauses.append(col(MessageFeedback.created_at) < naive_utc(end))
        if rating is not None:
            clauses.append(col(MessageFeedback.rating) == rating)
        return clauses

    async def list_page(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        rating: str | None,
        limit: int,
        after: tuple[datetime, str] | None = None,
    ) -> list[tuple[MessageFeedback, str]]:
        """Newest-first page ordered by ``(created_at DESC, id DESC)``.

        Returns ``(feedback, conversation_id)`` pairs; no prompt, answer or
        source text is selected.
        """
        stmt = (
            select(MessageFeedback, ChatMessage.conversation_id)
            .join(ChatMessage, ChatMessage.id == MessageFeedback.message_id)  # type: ignore[arg-type]
            .where(*self._filters(start=start, end=end, rating=rating))
        )
        if after is not None:
            ts, row_id = after
            stmt = stmt.where(
                or_(
                    col(MessageFeedback.created_at) < naive_utc(ts),
                    and_(
                        col(MessageFeedback.created_at) == naive_utc(ts),
                        col(MessageFeedback.id) < row_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            col(MessageFeedback.created_at).desc(), col(MessageFeedback.id).desc()
        ).limit(limit)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def summary(
        self, *, start: datetime | None, end: datetime | None, rating: str | None
    ) -> dict[str, Any]:
        up = func.coalesce(func.sum(case((col(MessageFeedback.rating) == "up", 1), else_=0)), 0)
        down = func.coalesce(func.sum(case((col(MessageFeedback.rating) == "down", 1), else_=0)), 0)
        result = await self.session.execute(
            select(up, down).where(*self._filters(start=start, end=end, rating=rating))
        )
        up_count, down_count = (int(v) for v in result.one())
        total = up_count + down_count
        return {
            "up": up_count,
            "down": down_count,
            "total": total,
            "positive_percentage": round(up_count * 100 / total, 1) if total else None,
        }

    async def message_for_feedback(
        self, conversation_id: str, message_id: str
    ) -> tuple[ChatMessage, ChatConversation] | None:
        """Load a message only when it belongs to the given conversation."""
        result = await self.session.execute(
            select(ChatMessage, ChatConversation)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)  # type: ignore[arg-type]
            .where(
                col(ChatMessage.id) == message_id,
                col(ChatMessage.conversation_id) == conversation_id,
            )
        )
        row = result.first()
        return (row[0], row[1]) if row else None
