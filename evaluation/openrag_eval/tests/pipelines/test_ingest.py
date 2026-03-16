import asyncio
import io
import logging
from pathlib import Path

import pytest
from openrag_sdk import OpenRAGClient
from ragworkbench.datasets_loader.data_models import DocumentObject, RagCorpus

from openrag_eval.pipelines.ingest import (
    ChunkingParams,
    EmbeddingModelParams,
    OpenRAGIngest,
    OpenRAGIngestArtifact,
    OpenRAGIngestParams,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def default_url():
    """Default URL for OpenRAG tests."""
    return "http://localhost:3000"


@pytest.fixture
def test_document():
    """Create a test document from real file."""
    # Path to the real test document
    file_name = "docling.pdf"

    doc_path = (
        Path(__file__).parent.parent.parent.parent
        / "dataset_sample"
        / "documents"
        / file_name
    )
    # Read the file content
    content = doc_path.read_bytes()
    stream = io.BytesIO(content)

    return DocumentObject(
        name=file_name,
        stream=stream,
        mime_type="image/pdf",
    )


@pytest.fixture
def test_rag_corpus(test_document):
    """Create a RagCorpus with a single test document."""
    return RagCorpus(documents=[test_document])


@pytest.fixture
def mock_data_loader(test_rag_corpus):
    """Create a mock data loader that returns the test corpus."""

    class MockDataLoader:
        def __init__(self, corpus):
            self.corpus = corpus
            self.dataset_name = "test_ingest_pipeline"

        def get_corpus(self):
            return self.corpus

    return MockDataLoader(test_rag_corpus)


@pytest.fixture
def ingest_params():
    """Create test ingestion parameters."""
    return OpenRAGIngestParams(
        embedding_model=EmbeddingModelParams(model_id="Azure/text-embedding-3-small-1"),
        chunking=ChunkingParams(
            chunk_size=256,
            chunk_overlap=25,
        ),
        ingestion_batch_size=5,
    )


class TestOpenRAGIngestPipeline:
    """
    Integration tests for OpenRAGIngest.
    These tests require a running OpenRAG backend at localhost:8000.
    """

    def test_ingest_single_document(
        self,
        ingest_params: OpenRAGIngestParams,
        mock_data_loader,
        test_document: DocumentObject,
    ):
        """
        Test ingesting a single document through the complete pipeline.

        This test:
        1. Creates an OpenRAGIngest with real SDK client
        2. Processes a single test document
        3. Waits for task completion using SDK's built-in wait functionality
        4. Verifies the returned artifact contains correct information

        Requires: Running OpenRAG backend at localhost:8000
        """
        logger.info("Starting test_ingest_single_document")

        # Create pipeline with real client
        pipeline = OpenRAGIngest(ingest_params)

        # Process the document
        logger.info(f"Processing document: {test_document.name}")
        artifacts = pipeline.process(data_loader=mock_data_loader)

        # Verify results
        assert len(artifacts) == 1, "Should return exactly one artifact"
        assert isinstance(
            artifacts[0], OpenRAGIngestArtifact
        ), "Should return OpenRAGIngestArtifact"

        artifact = artifacts[0]
        assert artifact.index_name.startswith(
            "documents_"
        ), "Index name should have correct prefix"
        assert len(artifact.index_name) > len(
            "documents_"
        ), "Index name should include hash"

        logger.info("✓ Successfully ingested document")
        logger.info(f"  Index name: {artifact.index_name}")

        # Verify document exists in index using SDK client (URL from environment)
        async def check_document_exists():
            async with OpenRAGClient() as sdk_client:
                return await sdk_client.documents.filename_exists(test_document.name)

        exists = asyncio.run(check_document_exists())
        assert (
            exists
        ), f"Document {test_document.name} should exist in index after ingestion"
        logger.info("✓ Verified document exists in index")

    def test_index_name_consistency(
        self, ingest_params: OpenRAGIngestParams, test_rag_corpus: RagCorpus
    ):
        """Test that index names are generated consistently for the same corpus."""
        logger.info("Starting test_index_name_consistency")

        pipeline = OpenRAGIngest(ingest_params)

        # Generate index name multiple times
        index_name_1 = pipeline._get_index_name(test_rag_corpus)  # type: ignore[attr-defined]
        index_name_2 = pipeline._get_index_name(test_rag_corpus)  # type: ignore[attr-defined]
        index_name_3 = pipeline._get_index_name(test_rag_corpus)  # type: ignore[attr-defined]

        # All should be identical
        assert (
            index_name_1 == index_name_2 == index_name_3
        ), "Index names should be consistent"
        assert index_name_1.startswith(
            "documents_"
        ), "Index name should have correct prefix"

        logger.info(f"✓ Index name generated consistently: {index_name_1}")

