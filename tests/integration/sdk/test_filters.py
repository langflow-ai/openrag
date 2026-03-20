"""Tests for knowledge filter CRUD and usage in chat/search."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestKnowledgeFilters:
    """Test knowledge filter create, read, update, delete and usage."""

    @pytest.mark.asyncio
    async def test_knowledge_filter_crud(self, client):
        """Full CRUD lifecycle for a knowledge filter."""
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
        assert any(f.name == "Python SDK Test Filter" for f in filters)

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

        updated_filter = await client.knowledge_filters.get(filter_id)
        assert updated_filter.description == "Updated description from Python SDK test"

        # Delete
        delete_success = await client.knowledge_filters.delete(filter_id)
        assert delete_success is True

        deleted_filter = await client.knowledge_filters.get(filter_id)
        assert deleted_filter is None

    @pytest.mark.asyncio
    async def test_filter_id_in_chat(self, client):
        """A filter_id can be passed to chat without error."""
        create_result = await client.knowledge_filters.create({
            "name": "Chat Test Filter Python",
            "description": "Filter for testing chat with filter_id",
            "queryData": {"query": "test", "limit": 5},
        })
        assert create_result.success is True
        filter_id = create_result.id

        try:
            response = await client.chat.create(
                message="Hello with filter",
                filter_id=filter_id,
            )
            assert response.response is not None
        finally:
            await client.knowledge_filters.delete(filter_id)

    @pytest.mark.asyncio
    async def test_filter_id_in_search(self, client):
        """A filter_id can be passed to search without error."""
        create_result = await client.knowledge_filters.create({
            "name": "Search Test Filter Python",
            "description": "Filter for testing search with filter_id",
            "queryData": {"query": "test", "limit": 5},
        })
        assert create_result.success is True
        filter_id = create_result.id

        try:
            results = await client.search.query("test query", filter_id=filter_id)
            assert results.results is not None
        finally:
            await client.knowledge_filters.delete(filter_id)
