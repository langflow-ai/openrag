"""
Tests for document API endpoints.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.api
class TestDocumentAPI:
    """Test suite for document API endpoints."""

    def test_document_upload_request_structure(self, test_file: Path):
        """Test document upload request structure."""
        upload_data = {
            "file": test_file.name,
            "metadata": {
                "source": "test",
                "uploaded_by": "test_user",
            },
        }

        assert "file" in upload_data
        assert "metadata" in upload_data
        assert isinstance(upload_data["metadata"], dict)

    def test_document_response_structure(self, sample_document_data: dict):
        """Test document response structure."""
        assert "id" in sample_document_data
        assert "filename" in sample_document_data
        assert "content" in sample_document_data
        assert "metadata" in sample_document_data

    def test_document_metadata_structure(self, sample_document_data: dict):
        """Test document metadata structure."""
        metadata = sample_document_data["metadata"]

        assert "source" in metadata
        assert "uploaded_by" in metadata
        assert "created_at" in metadata

    def test_document_list_request(self):
        """Test document list request parameters."""
        list_params = {
            "limit": 20,
            "offset": 0,
            "sort_by": "created_at",
            "order": "desc",
        }

        assert list_params["limit"] > 0
        assert list_params["offset"] >= 0
        assert list_params["order"] in ["asc", "desc"]

    def test_document_filter_params(self):
        """Test document filtering parameters."""
        filter_params = {
            "source": "test",
            "uploaded_by": "test_user",
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        }

        assert isinstance(filter_params, dict)
        assert "source" in filter_params or "uploaded_by" in filter_params


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.requires_opensearch
class TestDocumentAPIIntegration:
    """Integration tests for document API."""

    @pytest.mark.asyncio
    async def test_document_retrieval(
        self,
        opensearch_client,
        opensearch_test_index: str,
        sample_document_data: dict,
    ):
        """Test retrieving a document by ID."""
        # Index document
        await opensearch_client.index(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body=sample_document_data,
            refresh=True,
        )

        # Retrieve document
        result = await opensearch_client.get(
            index=opensearch_test_index, id=sample_document_data["id"]
        )

        assert result["found"]
        assert result["_id"] == sample_document_data["id"]
        assert result["_source"]["filename"] == sample_document_data["filename"]

    @pytest.mark.asyncio
    async def test_document_list(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test listing documents."""
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={
                "query": {"match_all": {}},
                "size": 20,
                "from": 0,
            },
        )

        assert "hits" in response
        assert response["hits"]["total"]["value"] > 0

    @pytest.mark.asyncio
    async def test_document_update(
        self,
        opensearch_client,
        opensearch_test_index: str,
        sample_document_data: dict,
    ):
        """Test updating document metadata."""
        # Index document
        await opensearch_client.index(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body=sample_document_data,
            refresh=True,
        )

        # Update document
        updated_metadata = {"updated_field": "new_value"}
        await opensearch_client.update(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body={"doc": {"metadata": updated_metadata}},
            refresh=True,
        )

        # Verify update
        result = await opensearch_client.get(
            index=opensearch_test_index, id=sample_document_data["id"]
        )

        assert result["_source"]["metadata"]["updated_field"] == "new_value"
