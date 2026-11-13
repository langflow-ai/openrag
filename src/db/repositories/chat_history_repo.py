"""CRUD for the durable, native OpenRAG chat history tables."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import case, delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import ChatConversation, ChatMessage


class ChatHistoryRepo:
    """Persist native-agent conversations and their complete event history."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_conversation(self, conversation_id: str) -> ChatConversation | None:
        return await self.session.get(ChatConversation, conversation_id)

    async def list_conversations(self, user_id: str, limit: int = 200) -> list[ChatConversation]:
        result = await self.session.execute(
            select(ChatConversation)
            .where(col(ChatConversation.user_id) == user_id)
            .order_by(col(ChatConversation.last_activity).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_conversation_ids(self, user_id: str) -> list[str]:
        """Return every native conversation id for cleanup ownership releases."""
        result = await self.session.execute(
            select(col(ChatConversation.id)).where(col(ChatConversation.user_id) == user_id)
        )
        return list(result.scalars().all())

    async def create_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        filter_id: str | None,
        title: str | None = None,
        total_messages: int = 0,
        created_at: datetime | None = None,
        last_activity: datetime | None = None,
    ) -> ChatConversation:
        now = datetime.now(UTC)
        row = ChatConversation(
            id=conversation_id,
            user_id=user_id,
            title=title,
            filter_id=filter_id,
            total_messages=total_messages,
            created_at=created_at or now,
            last_activity=last_activity or now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        result = await self.session.execute(
            select(ChatMessage)
            .where(col(ChatMessage.conversation_id) == conversation_id)
            .order_by(col(ChatMessage.sequence))
        )
        return list(result.scalars().all())

    async def list_messages_for_conversations(
        self, conversation_ids: list[str]
    ) -> list[ChatMessage]:
        """Return messages for a page of conversations in one query."""
        if not conversation_ids:
            return []
        result = await self.session.execute(
            select(ChatMessage)
            .where(col(ChatMessage.conversation_id).in_(conversation_ids))
            .order_by(col(ChatMessage.conversation_id), col(ChatMessage.sequence))
        )
        return list(result.scalars().all())

    async def append_message(
        self,
        *,
        conversation: ChatConversation,
        role: str,
        content: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        event_data: dict[str, Any] | None = None,
        error: bool = False,
        interrupted: bool = False,
    ) -> ChatMessage:
        now = datetime.now(UTC)
        total_messages_column = col(ChatConversation.total_messages)
        title_column = col(ChatConversation.title)
        values: dict[str, Any] = {
            "total_messages": total_messages_column + 1,
            "last_activity": now,
        }
        if role == "user" and content:
            title = content[:50] + ("..." if len(content) > 50 else "")
            values["title"] = case((title_column.is_(None), title), else_=title_column)
        result = await self.session.execute(
            update(ChatConversation)
            .where(col(ChatConversation.id) == conversation.id)
            .values(**values)
            .returning(total_messages_column)
        )
        total_messages = result.scalar_one_or_none()
        if total_messages is None:
            raise ValueError("Conversation was not found")
        sequence = total_messages - 1
        row = ChatMessage(
            # Conversation ids may use all 64 permitted characters, so do
            # not derive a message id from one. A UUID hex value is bounded
            # to 32 characters and remains unique across conversations.
            id=uuid4().hex,
            conversation_id=conversation.id,
            sequence=sequence,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            event_data=event_data,
            error=error,
            interrupted=interrupted,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(conversation)
        return row

    async def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return False
        await self.session.execute(
            delete(ChatMessage).where(col(ChatMessage.conversation_id) == conversation_id)
        )
        await self.session.delete(conversation)
        await self.session.flush()
        return True

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every native conversation and message owned by ``user_id``."""
        conversation_ids = select(ChatConversation.id).where(  # type: ignore[call-overload]
            col(ChatConversation.user_id) == user_id
        )
        await self.session.execute(
            delete(ChatMessage).where(col(ChatMessage.conversation_id).in_(conversation_ids))
        )
        result: CursorResult = await self.session.execute(  # type: ignore[assignment]
            delete(ChatConversation).where(col(ChatConversation.user_id) == user_id)
        )
        await self.session.flush()
        return result.rowcount or 0
