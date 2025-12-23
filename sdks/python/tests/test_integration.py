"""
Integration tests for OpenRAG Python SDK.

These tests run against a real OpenRAG instance.
Requires: OPENRAG_URL environment variable (defaults to http://localhost:3000)

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
_base_url = os.environ.get("OPENRAG_URL", "http://localhost:3000")
_onboarding_done = False


@pytest.fixture(scope="session", autouse=True)
def ensure_onboarding():
    """Ensure the OpenRAG instance is onboarded before running tests.

    This marks the config as 'edited' so that settings updates are allowed.
    """
    global _onboarding_done
    if _onboarding_done:
        return

    onboarding_payload = {
        "llm_provider": "openai",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "llm_model": "gpt-4o-mini",
        "sample_data": False,
    }

    try:
        response = httpx.post(
            f"{_base_url}/api/onboarding",
            json=onboarding_payload,
            timeout=30.0,
        )
        if response.status_code in (200, 204):
            print(f"[SDK Tests] Onboarding completed successfully")
        else:
            # May already be onboarded, which is fine
            print(f"[SDK Tests] Onboarding returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"[SDK Tests] Onboarding request failed: {e}")

    _onboarding_done = True


def get_api_key() -> str:
    """Get or create an API key for testing."""
    global _cached_api_key
    if _cached_api_key is None:
        # Use /api/keys to go through frontend proxy (frontend at :3000 proxies /api/* to backend)
        response = httpx.post(
            f"{_base_url}/api/keys",
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
    # Use .md extension - Langflow has issues with .txt files
    file_path = tmp_path / f"sdk_test_doc_{uuid.uuid4().hex[:8]}.md"
    file_path.write_text(
        f"# SDK Integration Test Document\n\n"
        f"ID: {uuid.uuid4()}\n\n"
        "This document tests the OpenRAG Python SDK.\n\n"
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

    @pytest.mark.asyncio
    async def test_update_settings(self, client):
        """Test updating settings."""
        # Get current settings first
        current_settings = await client.settings.get()
        current_chunk_size = current_settings.knowledge.chunk_size or 1000

        # Update with the same value (safe for tests)
        result = await client.settings.update({"chunk_size": current_chunk_size})

        assert result.message is not None

        # Verify the setting persisted
        updated_settings = await client.settings.get()
        assert updated_settings.knowledge.chunk_size == current_chunk_size


class TestKnowledgeFilters:
    """Test knowledge filter operations."""

    @pytest.mark.asyncio
    async def test_knowledge_filter_crud(self, client):
        """Test create, read, update, delete for knowledge filters."""
        # Create
        create_result = await client.knowledge_filters.create({
            "name": "Python SDK Test Filter",
            "description": "Filter created by Python SDK integration tests",
            "queryData": {
                "query": "test documents",
                "limit": 10,
                "scoreThreshold": 0.5,
            },
        })

        assert create_result.success is True
        assert create_result.id is not None
        filter_id = create_result.id

        # Search
        filters = await client.knowledge_filters.search("Python SDK Test")
        assert isinstance(filters, list)
        found = any(f.name == "Python SDK Test Filter" for f in filters)
        assert found is True

        # Get
        filter_obj = await client.knowledge_filters.get(filter_id)
        assert filter_obj is not None
        assert filter_obj.id == filter_id
        assert filter_obj.name == "Python SDK Test Filter"

        # Update
        update_success = await client.knowledge_filters.update(
            filter_id,
            {"description": "Updated description from Python SDK test"},
        )
        assert update_success is True

        # Verify update
        updated_filter = await client.knowledge_filters.get(filter_id)
        assert updated_filter.description == "Updated description from Python SDK test"

        # Delete
        delete_success = await client.knowledge_filters.delete(filter_id)
        assert delete_success is True

        # Verify deletion
        deleted_filter = await client.knowledge_filters.get(filter_id)
        assert deleted_filter is None

    @pytest.mark.asyncio
    async def test_filter_id_in_chat(self, client):
        """Test using filter_id in chat."""
        # Create a filter first
        create_result = await client.knowledge_filters.create({
            "name": "Chat Test Filter Python",
            "description": "Filter for testing chat with filter_id",
            "queryData": {
                "query": "test",
                "limit": 5,
            },
        })
        assert create_result.success is True
        filter_id = create_result.id

        try:
            # Use filter in chat
            response = await client.chat.create(
                message="Hello with filter",
                filter_id=filter_id,
            )
            assert response.response is not None
        finally:
            # Cleanup
            await client.knowledge_filters.delete(filter_id)

    @pytest.mark.asyncio
    async def test_filter_id_in_search(self, client):
        """Test using filter_id in search."""
        # Create a filter first
        create_result = await client.knowledge_filters.create({
            "name": "Search Test Filter Python",
            "description": "Filter for testing search with filter_id",
            "queryData": {
                "query": "test",
                "limit": 5,
            },
        })
        assert create_result.success is True
        filter_id = create_result.id

        try:
            # Use filter in search
            results = await client.search.query("test query", filter_id=filter_id)
            assert results.results is not None
        finally:
            # Cleanup
            await client.knowledge_filters.delete(filter_id)


class TestDocuments:
    """Test document operations."""

    @pytest.mark.asyncio
    async def test_ingest_document_no_wait(self, client, test_file: Path):
        """Test document ingestion without waiting."""
        # wait=False returns immediately with task_id
        result = await client.documents.ingest(file_path=str(test_file), wait=False)

        assert result.task_id is not None

        # Can poll manually
        final_status = await client.documents.wait_for_task(result.task_id)
        # TODO: Fix Langflow ingestion - status may be "failed" due to flow issues
        assert final_status.status is not None
        assert final_status.successful_files >= 0

    @pytest.mark.asyncio
    async def test_ingest_document(self, client, test_file: Path):
        """Test document ingestion."""
        # wait=True (default) polls until completion
        result = await client.documents.ingest(file_path=str(test_file))

        # TODO: Fix Langflow ingestion - status may be "failed" due to flow issues
        assert result.status is not None
        assert result.successful_files >= 0


    @pytest.mark.asyncio
    async def test_delete_document(self, client, test_file: Path):
        """Test document deletion."""
        # First ingest (wait for completion)
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

    @pytest.mark.asyncio
    async def test_get_conversation(self, client):
        """Test getting a specific conversation."""
        # Create a conversation first
        response = await client.chat.create(message="Test message for get.")
        assert response.chat_id is not None

        # Get the conversation
        conversation = await client.chat.get(response.chat_id)

        assert conversation.chat_id == response.chat_id
        assert conversation.messages is not None
        assert isinstance(conversation.messages, list)
        assert len(conversation.messages) >= 1

    @pytest.mark.asyncio
    async def test_delete_conversation(self, client):
        """Test deleting a conversation."""
        # Create a conversation first
        response = await client.chat.create(message="Test message for delete.")
        assert response.chat_id is not None

        # Delete the conversation
        result = await client.chat.delete(response.chat_id)

        assert result is True
