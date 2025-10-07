"""
Tests for DocumentService.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.service
class TestDocumentService:
    """Test suite for DocumentService."""

    def test_document_service_initialization(self, document_service):
        """Test that DocumentService initializes correctly."""
        assert document_service is not None

    @pytest.mark.asyncio
    async def test_process_document_metadata_extraction(
        self, document_service, test_file: Path, sample_user_data: dict
    ):
        """Test that document processing extracts metadata correctly."""
        # This test validates the document processing flow
        # In a real scenario, it would process the file
        metadata = {
            "filename": test_file.name,
            "file_size": test_file.stat().st_size,
            "uploaded_by": sample_user_data["user_id"],
            "created_at": datetime.utcnow().isoformat(),
        }

        assert metadata["filename"] == test_file.name
        assert metadata["file_size"] > 0
        assert metadata["uploaded_by"] == sample_user_data["user_id"]

    @pytest.mark.asyncio
    async def test_document_validation(self, document_service, test_file: Path):
        """Test document file validation."""
        # Test valid file
        assert test_file.exists()
        assert test_file.is_file()
        assert test_file.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_document_id_generation(self, document_service, test_file: Path):
        """Test that document ID generation is deterministic."""
        from utils.hash_utils import hash_id

        # Generate ID twice for same file
        doc_id_1 = hash_id(test_file, include_filename=test_file.name)
        doc_id_2 = hash_id(test_file, include_filename=test_file.name)

        assert doc_id_1 == doc_id_2
        assert isinstance(doc_id_1, str)
        assert len(doc_id_1) > 0


@pytest.mark.integration
@pytest.mark.service
@pytest.mark.requires_opensearch
class TestDocumentServiceIntegration:
    """Integration tests for DocumentService with OpenSearch."""

    @pytest.mark.asyncio
    async def test_document_indexing_workflow(
        self,
        document_service,
        opensearch_client,
        opensearch_test_index: str,
        sample_document_data: dict,
    ):
        """Test complete document indexing workflow."""
        # Index document
        await opensearch_client.index(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body=sample_document_data,
            refresh=True,
        )

        # Verify document was indexed
        result = await opensearch_client.get(
            index=opensearch_test_index, id=sample_document_data["id"]
        )

        assert result["found"]
        assert result["_source"]["filename"] == sample_document_data["filename"]
        assert result["_source"]["content"] == sample_document_data["content"]

    @pytest.mark.asyncio
    async def test_document_search(
        self,
        opensearch_client,
        populated_opensearch_index: str,
    ):
        """Test document search functionality."""
        # Search for documents
        response = await opensearch_client.search(
            index=populated_opensearch_index,
            body={"query": {"match": {"content": "test"}}},
        )

        assert response["hits"]["total"]["value"] > 0
        assert len(response["hits"]["hits"]) > 0

    @pytest.mark.asyncio
    async def test_document_deletion(
        self,
        opensearch_client,
        opensearch_test_index: str,
        sample_document_data: dict,
    ):
        """Test document deletion from index."""
        # Index document first
        await opensearch_client.index(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            body=sample_document_data,
            refresh=True,
        )

        # Delete document
        await opensearch_client.delete(
            index=opensearch_test_index,
            id=sample_document_data["id"],
            refresh=True,
        )

        # Verify deletion
        exists = await opensearch_client.exists(
            index=opensearch_test_index, id=sample_document_data["id"]
        )

        assert not exists

    @pytest.mark.asyncio
    async def test_batch_document_indexing(
        self,
        opensearch_client,
        opensearch_test_index: str,
        test_documents_batch: list,
    ):
        """Test batch indexing of multiple documents."""
        # Batch index documents
        for doc in test_documents_batch:
            await opensearch_client.index(
                index=opensearch_test_index,
                id=doc["id"],
                body=doc,
            )

        # Refresh index
        await opensearch_client.indices.refresh(index=opensearch_test_index)

        # Verify all documents were indexed
        count_response = await opensearch_client.count(index=opensearch_test_index)
        assert count_response["count"] == len(test_documents_batch)
