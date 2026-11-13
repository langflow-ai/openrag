"""DB-only persistence for the built-in OpenRAG chat agent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

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

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @classmethod
    async def sync_langflow_conversation_in_session(
        cls,
        repo: ChatHistoryRepo,
        *,
        conversation_id: str,
        user_id: str,
        title: str | None,
        filter_id: str | None,
        total_messages: int | None,
        created_at: datetime | str | None,
        last_activity: datetime | str | None,
        messages: list[dict[str, Any]],
        replace_history: bool = True,
    ) -> None:
        """Replace one Langflow thread's mirrored native history.

        Langflow remains the execution engine for its endpoint, but OpenRAG's
        database becomes the durable, user-visible history source. Replacing
        the mirror makes repeated synchronization idempotent and avoids
        duplicate streamed turns.
        """
        conversation = await repo.get_conversation(conversation_id)
        if conversation is None:
            conversation = await repo.create_conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                filter_id=filter_id,
                total_messages=0,
                created_at=cls._timestamp(created_at),
                last_activity=cls._timestamp(last_activity),
            )
        elif conversation.user_id != user_id:
            raise PermissionError("Conversation is not owned by this user")
        elif replace_history:
            await repo.delete_messages(conversation_id)
            conversation.title = title
            conversation.filter_id = filter_id
            conversation.total_messages = 0

        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            event_data: dict[str, Any] = {}
            if isinstance(message.get("chunks"), list):
                event_data["chunks"] = message["chunks"]
            response_data = message.get("response_data")
            if isinstance(response_data, dict) and response_data.get("usage"):
                event_data["usage"] = response_data["usage"]
            event_data["pydantic_messages"] = ModelMessagesTypeAdapter.dump_python(
                [
                    ModelRequest(parts=[UserPromptPart(content=content)])
                    if role == "user"
                    else ModelResponse(parts=[TextPart(content=content)])
                ],
                mode="json",
            )
            await repo.append_message(
                conversation=conversation,
                role=role,
                content=content,
                event_data=event_data,
                error=bool(message.get("error")),
                interrupted=bool(message.get("interrupted")),
                created_at=cls._timestamp(message.get("timestamp")),
            )

        conversation.title = title or conversation.title
        conversation.filter_id = filter_id
        conversation.total_messages = max(conversation.total_messages, total_messages or 0)
        conversation.created_at = cls._timestamp(created_at) or conversation.created_at
        conversation.last_activity = cls._timestamp(last_activity) or conversation.last_activity
        repo.session.add(conversation)
        await repo.session.flush()

    async def sync_langflow_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        title: str | None,
        filter_id: str | None,
        total_messages: int | None,
        created_at: datetime | str | None,
        last_activity: datetime | str | None,
        messages: list[dict[str, Any]],
        replace_history: bool = True,
    ) -> None:
        """Synchronize one Langflow conversation into the native history tables."""
        async with self._factory() as session:
            await self.sync_langflow_conversation_in_session(
                ChatHistoryRepo(session),
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                filter_id=filter_id,
                total_messages=total_messages,
                created_at=created_at,
                last_activity=last_activity,
                messages=messages,
                replace_history=replace_history,
            )
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
            rows_by_conversation: dict[str, list[Any]] = {
                conversation.id: [] for conversation in conversations
            }
            for row in await repo.list_messages_for_conversations(list(rows_by_conversation)):
                rows_by_conversation.setdefault(row.conversation_id, []).append(row)
            payload = []
            for conversation in conversations:
                messages = self._message_payload(rows_by_conversation[conversation.id])
                payload.append(
                    {
                        "response_id": conversation.id,
                        "title": conversation.title or "New chat",
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
