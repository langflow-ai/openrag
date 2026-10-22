"""Async CRUD over the ``session_ownership`` table."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import SessionOwnership


class SessionOwnershipRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, response_id: str) -> SessionOwnership | None:
        return await self.session.get(SessionOwnership, response_id)

    async def claim(
        self, response_id: str, user_id: str, conversation_id: str | None = None
    ) -> SessionOwnership:
        """Claim without transferring ownership or moving an existing alias."""
        existing = await self.get(response_id)
        now = datetime.now(UTC)
        canonical_id = conversation_id or response_id
        if canonical_id != response_id:
            canonical = await self.get(canonical_id)
            if canonical is None or canonical.user_id != user_id:
                raise PermissionError("Conversation is not owned by this user")
        if existing is None:
            row = SessionOwnership(
                response_id=response_id,
                user_id=user_id,
                conversation_id=canonical_id,
                created_at=now,
                last_accessed=now,
            )
            self.session.add(row)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                # Only primary-key/unique violations can be an INSERT race.
                # Never hide another constraint failure behind a matching row.
                if (
                    getattr(exc.orig, "sqlstate", None) != "23505"
                    and getattr(exc.orig, "sqlite_errorname", None)
                    != "SQLITE_CONSTRAINT_PRIMARYKEY"
                ):
                    raise
                # A failed flush leaves the transaction unusable. Roll it back
                # before reading the committed winner of an INSERT race.
                await self.session.rollback()
                existing = await self.get(response_id)
                if existing is None:
                    raise
                if canonical_id != response_id:
                    canonical = await self.get(canonical_id)
                    if canonical is None or canonical.user_id != user_id:
                        raise PermissionError("Conversation is not owned by this user") from None
            else:
                return row
        if existing.user_id != user_id or (
            (existing.conversation_id or response_id) != canonical_id
        ):
            raise PermissionError("Session ownership or conversation conflict")
        existing.conversation_id = canonical_id
        existing.last_accessed = now
        self.session.add(existing)
        await self.session.flush()
        return existing

    async def list_for_user(self, user_id: str) -> list[str]:
        result = await self.session.execute(
            select(col(SessionOwnership.response_id)).where(
                col(SessionOwnership.user_id) == user_id
            )
        )
        return list(result.scalars().all())

    async def list_for_conversation(self, conversation_id: str, user_id: str) -> list[str]:
        result = await self.session.execute(
            select(col(SessionOwnership.response_id)).where(
                col(SessionOwnership.user_id) == user_id,
                (col(SessionOwnership.conversation_id) == conversation_id)
                | (col(SessionOwnership.response_id) == conversation_id),
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
        created_at: datetime | None = None,
        last_accessed: datetime | None = None,
        conversation_id: str | None = None,
    ) -> bool:
        """Used by the runtime migration to copy JSON rows verbatim
        without overwriting timestamps. Returns True when a row was inserted."""
        existing = await self.get(response_id)
        if existing is not None:
            return False
        row = SessionOwnership(
            response_id=response_id,
            user_id=user_id,
            conversation_id=conversation_id or response_id,
            created_at=created_at or datetime.now(UTC),
            last_accessed=last_accessed,
        )
        self.session.add(row)
        await self.session.flush()
        return True
