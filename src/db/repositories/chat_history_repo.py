"""CRUD for the durable, native OpenRAG chat history tables."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
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
        sequence = conversation.total_messages
        row = ChatMessage(
            id=f"{conversation.id}:{sequence}",
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
        conversation.total_messages += 1
        conversation.last_activity = datetime.now(UTC)
        if role == "user" and not conversation.title and content:
            conversation.title = content[:50] + ("..." if len(content) > 50 else "")
        self.session.add(row)
        self.session.add(conversation)
        await self.session.flush()
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
        conversations = await self.list_conversations(user_id, limit=10_000)
        for conversation in conversations:
            await self.session.execute(
                delete(ChatMessage).where(col(ChatMessage.conversation_id) == conversation.id)
            )
            await self.session.delete(conversation)
        await self.session.flush()
        return len(conversations)
