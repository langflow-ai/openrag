"""Durable message and tool state for OpenRAG's native Python chat agent."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_chat_messages_conversation_sequence"
        ),
        Index("ix_chat_messages_conversation_sequence", "conversation_id", "sequence"),
    )

    id: str = Field(primary_key=True, max_length=64)
    conversation_id: str = Field(foreign_key="chat_conversations.id", max_length=64, index=True)
    sequence: int
    role: str = Field(max_length=32)
    content: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    tool_call_id: str | None = Field(default=None, max_length=128)
    tool_name: str | None = Field(default=None, max_length=128)
    tool_arguments: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    tool_result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    event_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: bool = Field(default=False)
    interrupted: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
