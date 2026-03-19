"""Integration tests for OpenRAGInference pipeline.

These tests require a running OpenRAG backend at localhost:8000 with documents already ingested.
The tests assume an index named 'documents' exists with test documents.
"""

import logging

import pytest
from ragworkbench.datasets_loader.data_models import (
    GroundTruthContextId,
    RagBenchmarkEntry,
)

from openrag_workbench.pipelines import (
    GenerativeModelParams,
    OpenRAGInference,
    OpenRAGInferenceParams,
    OpenRAGIngestArtifact,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def test_ingest_artifact():
    """
    Hardcoded ingest artifact for testing.
    Assumes the backend has an index with this name already set up.
    """
    return OpenRAGIngestArtifact(
        index_name="documents",
    )


@pytest.fixture
def inference_params():
    """Create test inference parameters."""
    return OpenRAGInferenceParams(
        generative_model=GenerativeModelParams(
            provider_id="openai",
            model_id="gpt-5.2",
            # provider_id="ollama",
            # model_id="gpt-oss:20b",
        ),
    )


@pytest.fixture
def test_benchmark_entry():
    """Create a test benchmark entry with a question about the document."""
    return RagBenchmarkEntry(
        question_id="test_q1",
        question="What is Docling?",
        ground_truth_answers=["Docling is a document processing library"],
        ground_truths_context_ids=[
            GroundTruthContextId(document_id="docling.pdf", page=1)
        ],
        is_answerable=True,
    )


class TestOpenRAGInference:
    """
    Integration tests for OpenRAGInference.

    Prerequisites:
    - Running OpenRAG backend at localhost:8000
    - Index named 'documents' with test documents ingested
    - ANTHROPIC_API_KEY environment variable set
    """

    def test_inference_single_entry(
        self,
        inference_params,
        test_ingest_artifact,
        test_benchmark_entry,
    ):
        """
        Test inference on a single benchmark entry.

        This test:
        1. Creates an OpenRAGInference pipeline with real client
        2. Sets the hardcoded ingest artifact
        3. Processes a single benchmark entry
        4. Verifies the returned InferenceResult contains an answer

        Requires: Running OpenRAG backend with 'documents' index already set up
        """
        logger.info("Starting test_inference_single_entry")
        logger.info(f"Question: {test_benchmark_entry.question}")
        logger.info(f"Using index: {test_ingest_artifact.index_name}")

        # Create inference pipeline
        inference = OpenRAGInference(
            params=inference_params,
            cache_dir=None,  # No caching for this test
        )

        # Set ingest artifacts
        logger.info(f"Setting ingest artifact: {test_ingest_artifact.index_name}")
        inference.set_ingest_artifacts([test_ingest_artifact])

        # Process the benchmark entry
        logger.info("Processing benchmark entry...")
        result = inference.process(test_benchmark_entry)

        # Verify results
        assert result is not None, "Result should not be None"
        assert result.answer is not None, "Answer should not be None"
        assert len(result.answer) > 0, "Answer should not be empty"
        assert result.question == test_benchmark_entry.question, "Question should match"
        assert (
            result.question_id == test_benchmark_entry.question_id
        ), "Question ID should match"

        logger.info("✓ Successfully generated answer")
        logger.info(f"  Question: {result.question}")
        logger.info(f"  Answer: {result.answer[:200]}...")  # First 200 chars

        # Verify context retrieval
        if result.context_ids:
            logger.info(f"  Retrieved {len(result.context_ids)} context(s)")
            for ctx_id in result.context_ids:
                logger.info(f"    - {ctx_id}")
        else:
            logger.warning("  No contexts retrieved")

    def test_inference_with_caching(
        self,
        inference_params,
        test_ingest_artifact,
        test_benchmark_entry,
        tmp_path,
    ):
        """
        Test inference with caching enabled.

        This test verifies that:
        1. First call generates and caches the result
        2. Second call retrieves from cache (should be faster)
        """
        logger.info("Starting test_inference_with_caching")

        cache_dir = tmp_path / "inference_cache"

        # Create inference pipeline with caching
        inference = OpenRAGInference(
            params=inference_params,
            cache_dir=str(cache_dir),
        )
        inference.set_ingest_artifacts([test_ingest_artifact])

        # Access the generation cache
        assert inference.generation_cache is not None, "Generation cache should be initialized"
        cache = inference.generation_cache

        # Verify initial cache state
        initial_cache_hit = cache.cache_hit
        initial_cache_miss = cache.cache_miss
        logger.info(f"Initial cache state - hits: {initial_cache_hit}, misses: {initial_cache_miss}")

        # First call - should generate and cache (cache miss)
        logger.info("First call (should generate)...")
        result1 = inference.process(test_benchmark_entry)
        assert result1.answer is not None
        logger.info(f"✓ First call completed: {result1.answer[:100]}...")

        # Verify cache miss occurred
        assert cache.cache_miss == initial_cache_miss + 1, "First call should result in cache miss"
        assert cache.cache_hit == initial_cache_hit, "First call should not result in cache hit"
        logger.info(f"✓ Cache miss recorded: {cache.cache_miss}")

        # Second call - should retrieve from cache (cache hit)
        logger.info("Second call (should use cache)...")
        result2 = inference.process(test_benchmark_entry)
        assert result2.answer is not None
        logger.info(f"✓ Second call completed: {result2.answer[:100]}...")

        # Verify cache hit occurred
        assert cache.cache_hit == initial_cache_hit + 1, "Second call should result in cache hit"
        assert cache.cache_miss == initial_cache_miss + 1, "Second call should not result in additional cache miss"
        logger.info(f"✓ Cache hit recorded: {cache.cache_hit}")

        # Results should be identical
        assert result1.answer == result2.answer, "Cached result should match original"
        assert result1.context_ids == result2.context_ids, "Context IDs should match"
        logger.info("✓ Cache working correctly - results match")

    def test_set_ingest_artifacts_validation(self, inference_params):
        """
        Test that set_ingest_artifacts validates input correctly.
        """
        logger.info("Starting test_set_ingest_artifacts_validation")

        inference = OpenRAGInference(params=inference_params, cache_dir=None)

        # Test with empty list
        with pytest.raises(ValueError, match="Expected exactly 1 ingest artifact"):
            inference.set_ingest_artifacts([])

        # Test with multiple artifacts
        artifact1 = OpenRAGIngestArtifact(
            index_name="test1",
        )
        artifact2 = OpenRAGIngestArtifact(
            index_name="test2",
        )

        with pytest.raises(ValueError, match="Expected exactly 1 ingest artifact"):
            inference.set_ingest_artifacts([artifact1, artifact2])

        logger.info("✓ Validation working correctly")

    def test_process_without_artifacts_raises_error(
        self,
        inference_params,
        test_benchmark_entry,
    ):
        """
        Test that processing without setting artifacts raises an error.
        """
        logger.info("Starting test_process_without_artifacts_raises_error")

        inference = OpenRAGInference(params=inference_params, cache_dir=None)

        # Try to process without setting artifacts
        with pytest.raises(RuntimeError, match="Ingest artifacts not set"):
            inference.process(test_benchmark_entry)

        logger.info("✓ Error raised correctly when artifacts not set")

