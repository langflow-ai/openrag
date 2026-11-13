"""DB-only persistence for the built-in OpenRAG chat agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter

from db.repositories import ChatHistoryRepo


class NativeChatHistoryService:
    """Store complete native-agent history independently from Langflow."""

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory()
        from db.engine import SessionLocal

        if SessionLocal is None:
            raise RuntimeError("Database is not initialized")
        return SessionLocal()

    async def start_conversation(
        self, conversation_id: str, user_id: str, filter_id: str | None
    ) -> None:
        async with self._factory() as session:
            repo = ChatHistoryRepo(session)
            existing = await repo.get_conversation(conversation_id)
            if existing is None:
                await repo.create_conversation(
                    conversation_id=conversation_id, user_id=user_id, filter_id=filter_id
                )
            elif existing.user_id != user_id:
                raise PermissionError("Conversation is not owned by this user")
            await session.commit()

    async def append(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        **message: Any,
    ) -> None:
        async with self._factory() as session:
            repo = ChatHistoryRepo(session)
            conversation = await repo.get_conversation(conversation_id)
            if conversation is None or conversation.user_id != user_id:
                raise PermissionError("Conversation is not owned by this user")
            await repo.append_message(conversation=conversation, role=role, **message)
            await session.commit()

    async def pydantic_history(self, conversation_id: str, user_id: str) -> list[Any]:
        """Restore the exact Pydantic AI wire history from completed turns."""
        async with self._factory() as session:
            repo = ChatHistoryRepo(session)
            conversation = await repo.get_conversation(conversation_id)
            if conversation is None or conversation.user_id != user_id:
                return []
            rows = await repo.list_messages(conversation_id)
        messages: list[Any] = []
        for row in rows:
            event_data = getattr(row, "event_data", None) or {}
            serialized = event_data.get("pydantic_messages")
            if not isinstance(serialized, list):
                continue
            try:
                messages.extend(ModelMessagesTypeAdapter.validate_python(serialized))
            except ValueError:
                # A corrupt historical turn should not make the user's whole
                # conversation unrecoverable. New turns remain wire-faithful.
                continue
        return messages

    async def owns_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Return whether a durable native conversation belongs to ``user_id``."""
        async with self._factory() as session:
            conversation = await ChatHistoryRepo(session).get_conversation(conversation_id)
            return conversation is not None and conversation.user_id == user_id

    async def history(self, user_id: str) -> dict[str, Any]:
        async with self._factory() as session:
            repo = ChatHistoryRepo(session)
            conversations = await repo.list_conversations(user_id)
            rows_by_conversation: dict[str, list[Any]] = {conversation.id: [] for conversation in conversations}
            for row in await repo.list_messages_for_conversations(list(rows_by_conversation)):
                rows_by_conversation.setdefault(row.conversation_id, []).append(row)
            payload = []
            for conversation in conversations:
                messages = self._message_payload(rows_by_conversation[conversation.id])
                payload.append(
                    {
                        "response_id": conversation.id,
                        "title": conversation.title or "New chat",
                        "endpoint": "chat",
                        "messages": messages,
                        "created_at": conversation.created_at.isoformat(),
                        "last_activity": conversation.last_activity.isoformat(),
                        "filter_id": conversation.filter_id,
                        "total_messages": conversation.total_messages,
                        "source": "database",
                    }
                )
        return {
            "user_id": user_id,
            "endpoint": "chat",
            "conversations": payload,
            "total_conversations": len(payload),
        }

    async def messages_for(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        """Return one owned conversation's display messages without loading all history."""
        async with self._factory() as session:
            repo = ChatHistoryRepo(session)
            conversation = await repo.get_conversation(conversation_id)
            if conversation is None or conversation.user_id != user_id:
                return []
            return self._message_payload(await repo.list_messages(conversation_id))

    @staticmethod
    def _message_payload(rows: list[Any]) -> list[dict[str, Any]]:
        """Translate durable message rows to the public chat-history schema."""
        messages: list[dict[str, Any]] = []
        for row in rows:
            if row.role not in {"user", "assistant"}:
                continue
            event_data = getattr(row, "event_data", None) or {}
            message: dict[str, Any] = {
                "role": row.role,
                "content": row.content or "",
                "timestamp": row.created_at.isoformat(),
                **({"error": True} if row.error else {}),
            }
            if row.role == "assistant" and isinstance(event_data.get("chunks"), list):
                message["chunks"] = event_data["chunks"]
            if row.role == "assistant" and event_data.get("usage"):
                message["response_data"] = {"usage": event_data["usage"]}
            messages.append(message)
        return messages

    async def delete(self, conversation_id: str, user_id: str) -> bool:
        async with self._factory() as session:
            deleted = await ChatHistoryRepo(session).delete_conversation(conversation_id, user_id)
            await session.commit()
            return deleted

    async def delete_all(self, user_id: str) -> int:
        async with self._factory() as session:
            deleted = await ChatHistoryRepo(session).delete_all_for_user(user_id)
            await session.commit()
            return deleted

    async def conversation_ids(self, user_id: str) -> list[str]:
        """Return all native conversation ids owned by ``user_id``."""
        async with self._factory() as session:
            return await ChatHistoryRepo(session).list_conversation_ids(user_id)
