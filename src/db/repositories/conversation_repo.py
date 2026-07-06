"""Async CRUD over the ``conversations`` table — chat-history metadata."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Conversation


class ConversationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, response_id: str) -> Optional[Conversation]:
        return await self.session.get(Conversation, response_id)

    async def list_for_user(
        self, user_id: str, limit: int = 200
    ) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.last_activity.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        response_id: str,
        user_id: str,
        title: Optional[str] = None,
        endpoint: Optional[str] = None,
        previous_response_id: Optional[str] = None,
        filter_id: Optional[str] = None,
        total_messages: int = 0,
        created_at: Optional[datetime] = None,
        last_activity: Optional[datetime] = None,
    ) -> Conversation:
        now = datetime.utcnow()
        existing = await self.get(response_id)
        if existing is None:
            row = Conversation(
                response_id=response_id,
                user_id=user_id,
                title=title,
                endpoint=endpoint,
                previous_response_id=previous_response_id,
                filter_id=filter_id,
                total_messages=total_messages,
                created_at=created_at or now,
                last_activity=last_activity or now,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        # Update non-null fields
        if title is not None:
            existing.title = title
        if endpoint is not None:
            existing.endpoint = endpoint
        if previous_response_id is not None:
            existing.previous_response_id = previous_response_id
        if filter_id is not None:
            existing.filter_id = filter_id
        if total_messages:
            existing.total_messages = total_messages
        existing.last_activity = last_activity or now
        self.session.add(existing)
        await self.session.flush()
        return existing

    async def delete(self, response_id: str, user_id: str) -> bool:
        """Delete only if the row is owned by user_id."""
        row = await self.get(response_id)
        if row is None or row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def delete_all_for_user(self, user_id: str) -> int:
        rows = await self.list_for_user(user_id, limit=10_000)
        for r in rows:
            await self.session.delete(r)
        await self.session.flush()
        return len(rows)

    async def to_metadata_dict(self, c: Conversation) -> dict[str, Any]:
        """JSON-shaped dict matching the legacy conversations.json
        per-conversation payload. Used by the service to keep API
        compatibility with existing call sites."""
        return {
            "response_id": c.response_id,
            "title": c.title,
            "endpoint": c.endpoint,
            "previous_response_id": c.previous_response_id,
            "filter_id": c.filter_id,
            "total_messages": c.total_messages or 0,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_activity": c.last_activity.isoformat() if c.last_activity else None,
        }
