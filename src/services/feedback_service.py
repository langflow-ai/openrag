"""Shared answer-feedback write path for browser and public /v1 callers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from db.models.message_feedback import MAX_FEEDBACK_COMMENT_LENGTH
from db.repositories import FeedbackRepo
from db.repositories.feedback_repo import MessageGoneError
from services.native_chat_history_service import NativeChatHistoryService

VALID_RATINGS = ("up", "down")


def serialize_feedback(row: Any) -> dict[str, Any]:
    return {
        "message_id": row.message_id,
        "rating": row.rating,
        "comment": row.comment,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


class FeedbackService:
    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    def _factory(self):
        if self._session_factory is not None:
            return self._session_factory()
        from db.engine import SessionLocal

        if SessionLocal is None:
            raise RuntimeError("Database is not initialized")
        return SessionLocal()

    async def submit(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
        rating: str,
        comment: str | None,
    ) -> dict[str, Any]:
        """Validate, authorise and upsert feedback in one owned transaction.

        ``user_id`` must be the canonical DB identity. Ownership is read from
        durable conversation rows in the same transaction as the write and is
        enforced regardless of RBAC state.
        """
        if rating not in VALID_RATINGS:
            raise HTTPException(status_code=422, detail={"error": "invalid_rating"})
        if comment is not None and len(comment) > MAX_FEEDBACK_COMMENT_LENGTH:
            raise HTTPException(status_code=422, detail={"error": "comment_too_long"})
        async with self._factory() as session:
            repo = FeedbackRepo(session)
            try:
                found = await repo.message_for_feedback(conversation_id, message_id)
                if found is None:
                    # Unknown conversation, unknown message, or a message that
                    # belongs to another conversation: same answer for all.
                    from db.repositories import ChatHistoryRepo

                    conversation = await ChatHistoryRepo(session).get_conversation(conversation_id)
                    if conversation is None:
                        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
                    if conversation.user_id != user_id:
                        raise HTTPException(status_code=403, detail={"error": "session_forbidden"})
                    raise HTTPException(status_code=404, detail={"error": "message_not_found"})
                message, conversation = found
                if conversation.user_id != user_id:
                    raise HTTPException(status_code=403, detail={"error": "session_forbidden"})
                if not NativeChatHistoryService.is_feedback_capable(message):
                    raise HTTPException(
                        status_code=422, detail={"error": "message_not_feedback_capable"}
                    )
                provenance = (message.event_data or {})["provenance"]
                try:
                    row = await repo.upsert(
                        user_id=user_id,
                        message_id=message.id,
                        rating=rating,
                        comment=comment,
                        model_provider=provenance.get("model_provider"),
                        model=provenance.get("model"),
                        retrieval=provenance.get("retrieval"),
                    )
                except MessageGoneError as exc:
                    raise HTTPException(
                        status_code=404, detail={"error": "message_not_found"}
                    ) from exc
                payload = serialize_feedback(row)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return payload
