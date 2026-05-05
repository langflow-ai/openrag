"""Session ownership — replaces ``data/session_ownership.json``.

Maps a chat session_id (== response_id) to the owning user. Used for
access-control checks: only the owning user can read/release a session.

The user_id column is intentionally NOT a foreign key — legacy JSON
state may reference user_ids that haven't been backfilled into the
``users`` table yet, and we don't want migration to fail on FK
violations.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SessionOwnership(SQLModel, table=True):
    __tablename__ = "session_ownership"

    response_id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = Field(default=None)
