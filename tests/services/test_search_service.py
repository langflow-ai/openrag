"""
Tests for SearchService.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.service
class TestSearchService:
    """Test suite for SearchService."""

    def test_search_service_initialization(self, search_service):
        """Test that SearchService initializes correctly."""
        assert search_service is not None

    def test_search_query_building(self, sample_search_query: dict):
        """Test search query structure."""
        assert "query" in sample_search_query
        assert "filters" in sample_search_query
        assert "limit" in sample_search_query

        assert isinstance(sample_search_query["query"], str)
        assert isinstance(sample_search_query["filters"], dict)
        assert isinstance(sample_search_query["limit"], int)

    def test_search_query_validation(self):
        """Test search query validation."""
        valid_query = {
            "query": "test search",
            "limit": 10,
        }

        assert valid_query["query"]
        assert valid_query["limit"] > 0

    def test_search_filters_structure(self, sample_search_query: dict):
        """Test search filters structure."""
        filters = sample_search_query["filters"]

        assert "source" in filters
        assert "date_range" in filters
        assert "start" in filters["date_range"]
        assert "end" in filters["date_range"]


@pytest.mark.integration
@pytest.mark.service
@pytest.mark.requires_opensearch
class TestSearchServiceIntegration:
    """Integration tests for SearchService with OpenSearch."""

    @pytest.mark.asyncio
    async def test_text_search(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test basic text search functionality."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match": {"content": "test document"}},
                "size": 10,
            },
        )

        assert "hits" in response
        assert response["hits"]["total"]["value"] > 0

    @pytest.mark.asyncio
    async def test_search_with_filters(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search with metadata filters."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {
                    "bool": {
                        "must": [{"match": {"content": "test"}}],
                        "filter": [{"term": {"metadata.type": "test"}}],
                    }
                },
                "size": 10,
            },
        )

        assert "hits" in response
        hits = response["hits"]["hits"]

        # Verify all results match the filter
        for hit in hits:
            assert hit["_source"]["metadata"]["type"] == "test"

    @pytest.mark.asyncio
    async def test_search_pagination(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search result pagination."""
        page_size = 5

        # First page
        response_page1 = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "size": page_size,
                "from": 0,
            },
        )

        # Second page
        response_page2 = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "size": page_size,
                "from": page_size,
            },
        )

        assert len(response_page1["hits"]["hits"]) <= page_size
        assert len(response_page2["hits"]["hits"]) <= page_size

        # Pages should have different results
        if len(response_page1["hits"]["hits"]) > 0 and len(response_page2["hits"]["hits"]) > 0:
            page1_ids = {hit["_id"] for hit in response_page1["hits"]["hits"]}
            page2_ids = {hit["_id"] for hit in response_page2["hits"]["hits"]}
            assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_search_sorting(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search result sorting."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "sort": [{"metadata.index": {"order": "asc"}}],
                "size": 10,
            },
        )

        hits = response["hits"]["hits"]
        if len(hits) > 1:
            # Verify sorting order
            indices = [hit["_source"]["metadata"]["index"] for hit in hits]
            assert indices == sorted(indices)

    @pytest.mark.asyncio
    async def test_fuzzy_search(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test fuzzy search for typo tolerance."""
        # Search with a typo
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {
                    "match": {
                        "content": {
                            "query": "documnt",  # typo
                            "fuzziness": "AUTO",
                        }
                    }
                },
                "size": 10,
            },
        )

        # Should still find documents with "document"
        assert "hits" in response

    @pytest.mark.asyncio
    async def test_aggregation_query(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test aggregation queries."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "size": 0,
                "aggs": {
                    "types": {
                        "terms": {
                            "field": "metadata.type",
                        }
                    }
                },
            },
        )

        assert "aggregations" in response
        assert "types" in response["aggregations"]

    @pytest.mark.asyncio
    async def test_search_highlighting(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test search result highlighting."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match": {"content": "test"}},
                "highlight": {
                    "fields": {
                        "content": {}
                    }
                },
                "size": 10,
            },
        )

        hits = response["hits"]["hits"]
        if len(hits) > 0:
            # At least some results should have highlights
            has_highlights = any("highlight" in hit for hit in hits)
            assert has_highlights or len(hits) == 0

    @pytest.mark.asyncio
    async def test_multi_field_search(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test searching across multiple fields."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {
                    "multi_match": {
                        "query": "test",
                        "fields": ["content", "filename"],
                    }
                },
                "size": 10,
            },
        )

        assert "hits" in response
        assert response["hits"]["total"]["value"] >= 0
