"""Persisted per-user answer feedback (thumbs up/down with an optional comment).

Feedback measures reported answer satisfaction. It is stored separately from
``audit_log`` and is deleted with its message/conversation or its user.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

MAX_FEEDBACK_COMMENT_LENGTH = 2000


class MessageFeedback(SQLModel, table=True):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_message_feedback_user_message"),
        CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating"),
        CheckConstraint(
            f"comment IS NULL OR length(comment) <= {MAX_FEEDBACK_COMMENT_LENGTH}",
            name="ck_message_feedback_comment_length",
        ),
        Index("ix_message_feedback_created", "created_at", "id"),
        Index("ix_message_feedback_rating_created", "rating", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=64)
    message_id: str = Field(
        sa_column=Column(
            String(64),
            ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: str = Field(
        sa_column=Column(
            String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    rating: str = Field(max_length=8)
    comment: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    model_provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    # NULL = unknown (historical answer); {"document_ids": [], "chunk_ids": []}
    # = known retrieval, possibly empty. Identifiers only, never retrieved text.
    retrieval: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # Timezone policy: timezone-aware UTC end to end. SQLModel maps ``datetime``
    # to its UTC-aware column type, the migration declares ``timezone=True``,
    # and the repository normalises every bound value with ``as_utc``.
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
