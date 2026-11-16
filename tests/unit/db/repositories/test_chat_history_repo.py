"""Regression tests for durable native-chat repository operations."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from db.models import ChatConversation, ChatMessage
from db.repositories.chat_history_repo import ChatHistoryRepo


@pytest.mark.asyncio
async def test_delete_all_for_user_removes_more_than_the_history_page_limit():
    """Bulk cleanup must not leave conversations beyond a 10,000-row page behind."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            session.add_all(
                [
                    ChatConversation(
                        id=f"alice-{number}",
                        user_id="alice",
                        filter_id=None,
                        total_messages=0,
                        created_at=now,
                        last_activity=now,
                    )
                    for number in range(10_001)
                ]
                + [
                    ChatConversation(
                        id="bob-1",
                        user_id="bob",
                        filter_id=None,
                        total_messages=1,
                        created_at=now,
                        last_activity=now,
                    )
                ]
            )
            session.add_all(
                [
                    ChatMessage(
                        id="alice-message",
                        conversation_id="alice-0",
                        sequence=0,
                        role="user",
                        content="Remove this message",
                    ),
                    ChatMessage(
                        id="bob-1:0",
                        conversation_id="bob-1",
                        sequence=0,
                        role="user",
                        content="Keep this message",
                    ),
                ]
            )
            await session.commit()

        async with factory() as session:
            deleted = await ChatHistoryRepo(session).delete_all_for_user("alice")
            await session.commit()

        async with factory() as session:
            repo = ChatHistoryRepo(session)
            assert deleted == 10_001
            assert await repo.list_conversations("alice", limit=1) == []
            assert await repo.list_messages("alice-0") == []
            assert (await repo.get_conversation("bob-1")) is not None
            assert len(await repo.list_messages("bob-1")) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_append_message_uses_a_bounded_id_for_a_maximum_length_conversation():
    """A message id must fit its column even when the conversation id does not."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            repo = ChatHistoryRepo(session)
            conversation = await repo.create_conversation(
                conversation_id="c" * 64,
                user_id="alice",
                filter_id=None,
            )
            message = await repo.append_message(
                conversation=conversation,
                role="user",
                content="Hello",
            )
            assert len(message.id) <= 64
            assert "c" * 64 not in message.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_stale_removes_expired_native_history_and_messages():
    """Retention removes native messages along with their expired conversation."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            session.add_all(
                [
                    ChatConversation(
                        id="expired",
                        user_id="alice",
                        filter_id=None,
                        total_messages=1,
                        created_at=now - timedelta(days=10),
                        last_activity=now - timedelta(days=10),
                    ),
                    ChatConversation(
                        id="current",
                        user_id="alice",
                        filter_id=None,
                        total_messages=1,
                        created_at=now,
                        last_activity=now,
                    ),
                ]
            )
            session.add_all(
                [
                    ChatMessage(
                        id="expired-message",
                        conversation_id="expired",
                        sequence=0,
                        role="user",
                        content="Old question",
                    ),
                    ChatMessage(
                        id="current-message",
                        conversation_id="current",
                        sequence=0,
                        role="user",
                        content="Current question",
                    ),
                ]
            )
            await session.commit()

        async with factory() as session:
            repo = ChatHistoryRepo(session)
            assert await repo.delete_stale(7) == 1
            await session.commit()

        async with factory() as session:
            repo = ChatHistoryRepo(session)
            assert await repo.get_conversation("expired") is None
            assert await repo.list_messages("expired") == []
            assert await repo.get_conversation("current") is not None
            assert len(await repo.list_messages("current")) == 1
    finally:
        await engine.dispose()
