"""Conversation metadata index — replaces ``data/conversations.json``.

Per-user chat history index. Stores the lightweight metadata about each
chat session (title, endpoint, timestamps, message count). Full message
bodies live in Langflow, not here.

The ``user_id`` column has no FK constraint for the same migration-safety
reason as ``session_ownership.user_id`` — legacy JSON may reference
ids not in the users table yet.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_recent", "user_id", "last_activity"),
    )

    response_id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(max_length=64, index=True)
    title: Optional[str] = Field(default=None, max_length=512)
    endpoint: Optional[str] = Field(default=None, max_length=64)
    previous_response_id: Optional[str] = Field(default=None, max_length=64)
    filter_id: Optional[str] = Field(default=None, max_length=128)
    total_messages: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
