"""Async CRUD over the ``session_ownership`` table."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SessionOwnership


class SessionOwnershipRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, response_id: str) -> Optional[SessionOwnership]:
        return await self.session.get(SessionOwnership, response_id)

    async def claim(
        self, response_id: str, user_id: str
    ) -> SessionOwnership:
        """Idempotent claim. If the row exists, only update last_accessed
        — never silently re-assign ownership (that would be a security
        bug). The caller is responsible for ensuring the user_id matches
        the existing owner before calling this for an existing row.
        """
        existing = await self.get(response_id)
        now = datetime.now(UTC)
        if existing is None:
            row = SessionOwnership(
                response_id=response_id,
                user_id=user_id,
                created_at=now,
                last_accessed=now,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        existing.last_accessed = now
        self.session.add(existing)
        await self.session.flush()
        return existing

    async def list_for_user(self, user_id: str) -> list[str]:
        result = await self.session.execute(
            select(SessionOwnership.response_id).where(
                SessionOwnership.user_id == user_id
            )
        )
        return list(result.scalars().all())

    async def is_owned_by(self, response_id: str, user_id: str) -> bool:
        row = await self.get(response_id)
        return row is not None and row.user_id == user_id

    async def release(self, response_id: str, user_id: str) -> bool:
        """Returns True if the row existed AND was owned by user_id."""
        row = await self.get(response_id)
        if row is None or row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def upsert_raw(
        self,
        response_id: str,
        user_id: str,
        created_at: Optional[datetime] = None,
        last_accessed: Optional[datetime] = None,
    ) -> bool:
        """Used by the runtime migration to copy JSON rows verbatim
        without overwriting timestamps. Returns True when a row was inserted."""
        existing = await self.get(response_id)
        if existing is not None:
            return False
        row = SessionOwnership(
            response_id=response_id,
            user_id=user_id,
            created_at=created_at or datetime.now(UTC),
            last_accessed=last_accessed,
        )
        self.session.add(row)
        await self.session.flush()
        return True
