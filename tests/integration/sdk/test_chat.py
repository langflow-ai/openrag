"""Tests for the chat endpoint — non-streaming, streaming, conversations, and RAG."""

import os
from pathlib import Path

import pytest
from openrag_sdk import Source

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestChat:
    """Core chat operation tests."""

    @pytest.mark.asyncio
    async def test_chat_non_streaming(self, client):
        """Non-streaming chat returns a non-empty response string."""
        response = await client.chat.create(message="Say hello in exactly 3 words.")
        try:
            assert response.response is not None
            assert isinstance(response.response, str)
            assert len(response.response) > 0
            assert response.sources is not None
            assert isinstance(response.sources, list)
            for s in response.sources:
                assert isinstance(s, Source)
                # score is a raw OpenSearch relevance score (boosted BM25/KNN
                # hybrid), not normalized to [0, 1] -- it can exceed 1.
                assert s.score >= 0
        finally:
            if response.chat_id:
                await client.chat.delete(response.chat_id)

    @pytest.mark.asyncio
    async def test_chat_with_filters_limit_and_score_threshold(self, client, test_file: Path):
        """filters, limit, and score_threshold together must be accepted and honoured."""
        await client.documents.ingest(file_path=str(test_file))
        response = None
        try:
            response = await client.chat.create(
                message="What does the document say about elephants?",
                filters={"data_sources": [test_file.name]},
                limit=3,
                score_threshold=0.0,
            )
            assert response.sources is not None
            assert len(response.sources) <= 3
        finally:
            if response is not None and response.chat_id:
                await client.chat.delete(response.chat_id)
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_chat_streaming_create(self, client):
        """create(stream=True) yields content events with text deltas, ending in done."""
        collected_text = ""
        events = []

        async for event in await client.chat.create(
            message="Say 'test' and nothing else.",
            stream=True,
        ):
            events.append(event)
            if event.type == "content":
                collected_text += event.delta

        try:
            assert len(collected_text) > 0
            assert len(events) > 0
            assert events[-1].type == "done"
            assert events[-1].chat_id is not None
        finally:
            chat_id = events[-1].chat_id if events else None
            if chat_id:
                await client.chat.delete(chat_id)

    @pytest.mark.asyncio
    async def test_chat_streaming_context_manager(self, client):
        """stream() context manager accumulates text in stream.text."""
        async with client.chat.stream(message="Say 'hello' and nothing else.") as stream:
            async for _ in stream:
                pass
            assert len(stream.text) > 0

        if stream.chat_id:
            await client.chat.delete(stream.chat_id)

    @pytest.mark.asyncio
    async def test_chat_text_stream(self, client):
        """text_stream yields plain text deltas."""
        collected = ""

        async with client.chat.stream(message="Say 'world' and nothing else.") as stream:
            async for text in stream.text_stream:
                collected += text

        try:
            assert len(collected) > 0
        finally:
            if stream.chat_id:
                await client.chat.delete(stream.chat_id)

    @pytest.mark.asyncio
    async def test_chat_final_text(self, client):
        """final_text() returns the complete accumulated response."""
        async with client.chat.stream(message="Say 'done' and nothing else.") as stream:
            text = await stream.final_text()

        try:
            assert len(text) > 0
        finally:
            if stream.chat_id:
                await client.chat.delete(stream.chat_id)

    @pytest.mark.asyncio
    async def test_chat_conversation_continuation(self, client):
        """A second message with chat_id continues the same conversation."""
        response1 = await client.chat.create(message="Remember the number 42.")
        assert response1.chat_id is not None
        chat_id = response1.chat_id

        try:
            response2 = await client.chat.create(
                message="What number did I ask you to remember?",
                chat_id=chat_id,
            )
            assert response2.response is not None
            followup = response2
            assert followup.chat_id == chat_id
        finally:
            await client.chat.delete(chat_id)

    @pytest.mark.asyncio
    async def test_list_conversations(self, client):
        """list() returns a ConversationListResponse with a list of conversations."""
        created = await client.chat.create(message="Test message for listing.")
        assert created.chat_id is not None

        try:
            result = await client.chat.list()

            assert result.conversations is not None
            assert isinstance(result.conversations, list)
            assert len(result.conversations) >= 1

            conv = result.conversations[0]
            assert isinstance(conv.title, str)
            assert isinstance(conv.created_at, str) and len(conv.created_at) > 0
            assert isinstance(conv.last_activity, str) and len(conv.last_activity) > 0
            assert conv.message_count >= 0
        finally:
            await client.chat.delete(created.chat_id)

    @pytest.mark.asyncio
    async def test_get_conversation(self, client):
        """get() returns the full conversation with message history."""
        response = await client.chat.create(message="Test message for get.")
        assert response.chat_id is not None

        try:
            conversation = await client.chat.get(response.chat_id)

            assert conversation.chat_id == response.chat_id
            assert conversation.messages is not None
            assert isinstance(conversation.messages, list)
            assert len(conversation.messages) >= 1

            msg = conversation.messages[0]
            assert msg.role in ("user", "assistant")
            assert isinstance(msg.content, str)
        finally:
            await client.chat.delete(response.chat_id)

    @pytest.mark.asyncio
    async def test_delete_conversation(self, client):
        """delete() returns True for a conversation that exists."""
        response = await client.chat.create(message="Test message for delete.")
        assert response.chat_id is not None

        result = await client.chat.delete(response.chat_id)

        assert result is True

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Structured source extraction is being fixed in a follow-up PR")
    async def test_chat_with_sources(self, client, test_file: Path):
        """Chat response must cite the ingested document as a source (RAG)."""
        result = await client.documents.ingest(file_path=str(test_file))
        if result.status == "failed" or result.successful_files == 0:
            pytest.skip("Document ingestion failed — cannot test RAG sources")

        response = await client.chat.create(
            message="What is the color of the dancing animals mentioned in my documents?"
        )

        assert response.sources is not None
        assert len(response.sources) > 0
        source_filenames = [s.filename for s in response.sources]
        assert any(test_file.name in name for name in source_filenames)


class TestChatExtended:
    """Additional chat edge-case tests."""

    @pytest.mark.asyncio
    async def test_stream_continuation_with_chat_id(self, client):
        """Streaming a follow-up message in an existing conversation works."""
        r1 = await client.chat.create(message="Remember the colour blue.")
        assert r1.chat_id is not None

        try:
            collected = ""
            async with client.chat.stream(
                message="What colour did I ask you to remember?",
                chat_id=r1.chat_id,
            ) as stream:
                async for text in stream.text_stream:
                    collected += text

            assert len(collected) > 0
        finally:
            await client.chat.delete(r1.chat_id)

    @pytest.mark.asyncio
    async def test_chat_response_has_chat_id(self, client):
        """Every non-streaming response must include a chat_id for continuation."""
        response = await client.chat.create(message="Hello.")
        try:
            assert response.chat_id is not None
            assert isinstance(response.chat_id, str)
            assert len(response.chat_id) > 0
        finally:
            await client.chat.delete(response.chat_id)

    @pytest.mark.asyncio
    async def test_stream_chat_id_available_after_iteration(self, client):
        """chat_id must be populated on ChatStream after the stream is consumed."""
        async with client.chat.stream(message="Say one word.") as stream:
            await stream.final_text()
            assert stream.chat_id is not None

        if stream.chat_id:
            await client.chat.delete(stream.chat_id)

    @pytest.mark.asyncio
    async def test_list_conversations_returns_list(self, client):
        """list() always returns a ConversationListResponse with a list."""
        result = await client.chat.list()
        assert isinstance(result.conversations, list)
