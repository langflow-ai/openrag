"""
Integration tests for OpenRAG Python SDK.

These tests run against a real OpenRAG instance.
Requires: OPENRAG_URL environment variable (defaults to http://localhost:8000)

Run with: pytest sdks/python/tests/test_integration.py -v
"""

import os
from pathlib import Path

import httpx
import pytest

# Skip all tests if no OpenRAG instance is available
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)

# Module-level cache for API key (created once, reused)
_cached_api_key: str | None = None
_base_url = os.environ.get("OPENRAG_URL", "http://localhost:8000")


def get_api_key() -> str:
    """Get or create an API key for testing."""
    global _cached_api_key
    if _cached_api_key is None:
        response = httpx.post(
            f"{_base_url}/keys",
            json={"name": "SDK Integration Test"},
            timeout=30.0,
        )
        if response.status_code == 401:
            pytest.skip("Cannot create API key - authentication required")
        assert response.status_code == 200, f"Failed to create API key: {response.text}"
        _cached_api_key = response.json()["api_key"]
    return _cached_api_key


@pytest.fixture
def client():
    """Create an OpenRAG client for each test."""
    from openrag_sdk import OpenRAGClient

    return OpenRAGClient(api_key=get_api_key(), base_url=_base_url)


@pytest.fixture
def test_file(tmp_path) -> Path:
    """Create a test file for ingestion with unique content."""
    import uuid
    file_path = tmp_path / f"sdk_test_doc_{uuid.uuid4().hex[:8]}.txt"
    file_path.write_text(
        f"SDK Integration Test Document {uuid.uuid4()}\n\n"
        "This document tests the OpenRAG Python SDK.\n"
        "It contains unique content about purple elephants dancing.\n"
    )
    return file_path


class TestSettings:
    """Test settings endpoint."""

    @pytest.mark.asyncio
    async def test_get_settings(self, client):
        """Test getting settings."""
        settings = await client.settings.get()

        assert settings.agent is not None
        assert settings.knowledge is not None


class TestDocuments:
    """Test document operations."""

    @pytest.mark.asyncio
    async def test_ingest_document(self, client, test_file: Path):
        """Test document ingestion."""
        result = await client.documents.ingest(file_path=str(test_file))

        assert result.success is True
        assert result.chunks > 0

    @pytest.mark.asyncio
    async def test_delete_document(self, client, test_file: Path):
        """Test document deletion."""
        # First ingest
        await client.documents.ingest(file_path=str(test_file))

        # Then delete
        result = await client.documents.delete(test_file.name)

        assert result.success is True


class TestSearch:
    """Test search operations."""

    @pytest.mark.asyncio
    async def test_search_query(self, client, test_file: Path):
        """Test search query."""
        # Ensure document is ingested
        await client.documents.ingest(file_path=str(test_file))

        # Wait a bit for indexing
        import asyncio
        await asyncio.sleep(2)

        # Search for unique content
        results = await client.search.query("purple elephants dancing")

        assert results.results is not None
        # Note: might be empty if indexing is slow, that's ok for CI


class TestChat:
    """Test chat operations."""

    @pytest.mark.asyncio
    async def test_chat_non_streaming(self, client):
        """Test non-streaming chat."""
        response = await client.chat.create(
            message="Say hello in exactly 3 words."
        )

        assert response.response is not None
        assert isinstance(response.response, str)
        assert len(response.response) > 0

    @pytest.mark.asyncio
    async def test_chat_streaming_create(self, client):
        """Test streaming chat with create(stream=True)."""
        collected_text = ""

        async for event in await client.chat.create(
            message="Say 'test' and nothing else.",
            stream=True,
        ):
            if event.type == "content":
                collected_text += event.delta

        assert len(collected_text) > 0

    @pytest.mark.asyncio
    async def test_chat_streaming_context_manager(self, client):
        """Test streaming chat with stream() context manager."""
        async with client.chat.stream(
            message="Say 'hello' and nothing else."
        ) as stream:
            async for _ in stream:
                pass

            # Check aggregated properties
            assert len(stream.text) > 0

    @pytest.mark.asyncio
    async def test_chat_text_stream(self, client):
        """Test text_stream helper."""
        collected = ""

        async with client.chat.stream(
            message="Say 'world' and nothing else."
        ) as stream:
            async for text in stream.text_stream:
                collected += text

        assert len(collected) > 0

    @pytest.mark.asyncio
    async def test_chat_final_text(self, client):
        """Test final_text() helper."""
        async with client.chat.stream(
            message="Say 'done' and nothing else."
        ) as stream:
            text = await stream.final_text()

        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_chat_conversation_continuation(self, client):
        """Test continuing a conversation."""
        # First message
        response1 = await client.chat.create(
            message="Remember the number 42."
        )
        assert response1.chat_id is not None

        # Continue conversation
        response2 = await client.chat.create(
            message="What number did I ask you to remember?",
            chat_id=response1.chat_id,
        )
        assert response2.response is not None

    @pytest.mark.asyncio
    async def test_list_conversations(self, client):
        """Test listing conversations."""
        # Create a conversation first
        await client.chat.create(message="Test message for listing.")

        # List conversations
        result = await client.chat.list()

        assert result.conversations is not None
        assert isinstance(result.conversations, list)
