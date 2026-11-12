"""Async CRUD over the ``failed_ingestion`` table."""

import os
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import FailedIngestion

DEFAULT_MAX_ATTEMPTS = 3
_MAX_ERROR_CHARS = 2000


def max_attempts() -> int:
    """Failures tolerated before a file is skipped (``FAILED_INGESTION_MAX_ATTEMPTS``)."""
    raw = os.getenv("FAILED_INGESTION_MAX_ATTEMPTS")
    try:
        value = int(raw) if raw else DEFAULT_MAX_ATTEMPTS
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return value if value > 0 else DEFAULT_MAX_ATTEMPTS


class FailedIngestionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: str, connector_type: str, file_id: str) -> FailedIngestion | None:
        result = await self.session.execute(
            select(FailedIngestion).where(
                col(FailedIngestion.user_id) == user_id,
                col(FailedIngestion.connector_type) == connector_type,
                col(FailedIngestion.file_id) == file_id,
            )
        )
        return result.scalar_one_or_none()

    async def record_failure(
        self,
        user_id: str,
        connector_type: str,
        file_id: str,
        error: str | None,
        filename: str | None = None,
        content_etag: str | None = None,
        modified_time: str | None = None,
    ) -> FailedIngestion:
        """Record one failed attempt.

        Repeats against the same source version add to ``attempt_count``. When
        the stored version differs from this one the file was changed at the
        source in between, so the count starts again at 1.
        """
        now = datetime.now(UTC)
        error = error[:_MAX_ERROR_CHARS] if error else error
        existing = await self.get(user_id, connector_type, file_id)
        if existing is None:
            row = FailedIngestion(
                id=uuid.uuid4().hex,
                user_id=user_id,
                connector_type=connector_type,
                file_id=file_id,
                filename=filename,
                content_etag=content_etag,
                modified_time=modified_time,
                last_error=error,
                attempt_count=1,
                first_failed_at=now,
                last_failed_at=now,
            )
            self.session.add(row)
            await self.session.flush()
            return row

        same_version = (
            existing.content_etag == content_etag and existing.modified_time == modified_time
        )
        existing.attempt_count = existing.attempt_count + 1 if same_version else 1
        existing.filename = filename or existing.filename
        existing.content_etag = content_etag
        existing.modified_time = modified_time
        existing.last_error = error
        existing.last_failed_at = now
        self.session.add(existing)
        await self.session.flush()
        return existing

    async def list_for_user(
        self, user_id: str, connector_type: str | None = None
    ) -> list[FailedIngestion]:
        stmt = select(FailedIngestion).where(col(FailedIngestion.user_id) == user_id)
        if connector_type:
            stmt = stmt.where(col(FailedIngestion.connector_type) == connector_type)
        stmt = stmt.order_by(col(FailedIngestion.last_failed_at).desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def clear(self, user_id: str, connector_type: str, file_id: str) -> bool:
        """Remove one entry. Returns True when a row existed."""
        result = cast(
            CursorResult,
            await self.session.execute(
                delete(FailedIngestion).where(
                    col(FailedIngestion.user_id) == user_id,
                    col(FailedIngestion.connector_type) == connector_type,
                    col(FailedIngestion.file_id) == file_id,
                )
            ),
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def clear_all(self, user_id: str, connector_type: str | None = None) -> int:
        """Remove every entry for the user (optionally one connector). Returns the count."""
        stmt = delete(FailedIngestion).where(col(FailedIngestion.user_id) == user_id)
        if connector_type:
            stmt = stmt.where(col(FailedIngestion.connector_type) == connector_type)
        result = cast(CursorResult, await self.session.execute(stmt))
        await self.session.flush()
        return result.rowcount or 0
