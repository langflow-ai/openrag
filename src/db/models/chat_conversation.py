"""Durable conversation metadata for OpenRAG's native Python chat agent."""

from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class ChatConversation(SQLModel, table=True):
    __tablename__ = "chat_conversations"
    __table_args__ = (Index("ix_chat_conversations_user_recent", "user_id", "last_activity"),)

    id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(max_length=64, index=True)
    title: str | None = Field(default=None, max_length=512)
    filter_id: str | None = Field(default=None, max_length=128)
    total_messages: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(UTC))
