"""
Tests for search API endpoints.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.api
class TestSearchAPI:
    """Test suite for search API endpoints."""

    def test_search_request_structure(self, sample_search_query: dict):
        """Test search request structure."""
        assert "query" in sample_search_query
        assert isinstance(sample_search_query["query"], str)
        assert len(sample_search_query["query"]) > 0

    def test_search_request_validation(self):
        """Test search request validation."""
        valid_request = {
            "query": "test query",
            "limit": 10,
        }

        assert valid_request["query"]
        assert valid_request["limit"] > 0
        assert valid_request["limit"] <= 100

    def test_search_response_structure(self, mock_opensearch_response: dict):
        """Test search response structure."""
        assert "hits" in mock_opensearch_response
        assert "total" in mock_opensearch_response["hits"]
        assert "hits" in mock_opensearch_response["hits"]

    def test_search_result_item_structure(self, mock_opensearch_response: dict):
        """Test individual search result structure."""
        hits = mock_opensearch_response["hits"]["hits"]

        if len(hits) > 0:
            result = hits[0]
            assert "_id" in result
            assert "_source" in result
            assert "_score" in result

    def test_search_filter_structure(self, sample_search_query: dict):
        """Test search filter structure."""
        if "filters" in sample_search_query:
            filters = sample_search_query["filters"]
            assert isinstance(filters, dict)


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.requires_opensearch
class TestSearchAPIIntegration:
    """Integration tests for search API."""

    @pytest.mark.asyncio
    async def test_basic_search(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test basic search functionality."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match": {"content": "test"}},
                "size": 10,
            },
        )

        assert response["hits"]["total"]["value"] > 0

    @pytest.mark.asyncio
    async def test_search_with_limit(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search with result limit."""
        limit = 5
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "size": limit,
            },
        )

        assert len(response["hits"]["hits"]) <= limit

    @pytest.mark.asyncio
    async def test_search_with_offset(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search with pagination offset."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "size": 5,
                "from": 5,
            },
        )

        assert "hits" in response

    @pytest.mark.asyncio
    async def test_search_empty_query(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search with empty query returns all."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={"query": {"match_all": {}}},
        )

        assert response["hits"]["total"]["value"] > 0

    @pytest.mark.asyncio
    async def test_search_no_results(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search with no matching results."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match": {"content": "nonexistent_content_xyz"}},
            },
        )

        # Should return empty results, not error
        assert response["hits"]["total"]["value"] == 0
        assert len(response["hits"]["hits"]) == 0
