"""Langflow conversation metadata index — replaces ``data/conversations.json``.

Stores lightweight metadata for conversations executed by Langflow. Full
message bodies remain in Langflow; native OpenRAG chat uses
``chat_conversations`` and ``chat_messages`` instead.

The ``user_id`` column has no FK constraint for the same migration-safety
reason as ``session_ownership.user_id`` — legacy JSON may reference
ids not in the users table yet.
"""

from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class LangflowConversation(SQLModel, table=True):
    __tablename__ = "langflow_conversations"
    __table_args__ = (Index("ix_langflow_conversations_user_recent", "user_id", "last_activity"),)

    response_id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(max_length=64, index=True)
    title: str | None = Field(default=None, max_length=512)
    endpoint: str | None = Field(default=None, max_length=64)
    previous_response_id: str | None = Field(default=None, max_length=64)
    filter_id: str | None = Field(default=None, max_length=128)
    total_messages: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(UTC))


# Backwards-compatible import for integrations that still import Conversation.
Conversation = LangflowConversation
