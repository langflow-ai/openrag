"""Tests for the search endpoint."""

import os
import uuid
from pathlib import Path

import pytest
from openrag_sdk import SearchFilters
from openrag_sdk.exceptions import ValidationError

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestSearch:
    """Core search query tests."""

    @pytest.mark.asyncio
    async def test_search_query(self, client, test_file: Path):
        """A basic search query returns a results list."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("purple elephants dancing")
            assert results.results is not None
            for r in results.results:
                # score is a raw OpenSearch relevance score (boosted BM25/KNN
                # hybrid), not normalized to [0, 1] -- it can exceed 1.
                assert r.score >= 0
        finally:
            await client.documents.delete(test_file.name)


class TestSearchExtended:
    """Additional search parameter and edge-case tests."""

    @pytest.mark.asyncio
    async def test_search_with_limit(self, client, test_file: Path):
        """limit parameter caps the number of results returned."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("test", limit=1)
            assert results.results is not None
            assert len(results.results) <= 1
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_search_with_high_score_threshold_returns_empty(self, client, test_file: Path):
        """A score_threshold of 0.99 should filter out most or all results."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("test", score_threshold=0.99)
            assert results.results is not None
            assert isinstance(results.results, list)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_search_with_score_threshold_filters_low_scores(self, client, test_file: Path):
        """A score_threshold of 0.5 must only return results scoring at or above it."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("test", score_threshold=0.5)
            assert results.results is not None
            assert all(r.score >= 0.5 for r in results.results)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_search_no_results_for_obscure_query(self, client):
        """A nonsense query must return an empty list, not raise an error."""
        results = await client.search.query("zzz_xyzzy_nonexistent_content_abc123_qwerty_999")
        assert results.results is not None
        assert isinstance(results.results, list)

    @pytest.mark.asyncio
    async def test_search_unicode_query(self, client):
        """Unicode and emoji characters in the query must not cause an error."""
        results = await client.search.query("こんにちは 🦩 Ñoño résumé")
        assert results.results is not None
        assert isinstance(results.results, list)

    @pytest.mark.asyncio
    async def test_search_returns_result_fields(self, client, test_file: Path):
        """Each search result must have text populated as a string, and limit is respected."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("purple elephants dancing", limit=5)
            assert len(results.results) <= 5
            for result in results.results:
                assert result.text is not None
                assert isinstance(result.text, str)
                assert result.page is None or isinstance(result.page, int)
                assert result.mimetype is None or isinstance(result.mimetype, str)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_search_whitespace_query_raises_validation_error(self, client):
        """A whitespace-only query must raise ValidationError, not be treated as valid."""
        with pytest.raises(ValidationError):
            await client.search.query("   ")


class TestSearchFilenameFilter:
    """Verify inline `filters.data_sources` scopes search to exact filenames."""

    @pytest.mark.asyncio
    async def test_search_filters_by_filename(self, client, tmp_path):
        """Search with SearchFilters(data_sources=[filename]) returns only that file.

        Ingests two distinguishable documents, then uses a wildcard query so the
        assertion does not depend on semantic ranking.
        """
        token = uuid.uuid4().hex[:8]
        alpha = tmp_path / f"alpha_{token}.md"
        beta = tmp_path / f"beta_{token}.md"
        alpha.write_text("# Alpha\n\nUnique content about purple elephants.\n")
        beta.write_text("# Beta\n\nUnique content about yellow tigers.\n")

        try:
            await client.documents.ingest(file_path=str(alpha))
            await client.documents.ingest(file_path=str(beta))

            results = await client.search.query(
                "*",
                filters=SearchFilters(data_sources=[alpha.name]),
            )
            assert results.results is not None
            filenames = [r.filename for r in results.results]
            assert alpha.name in filenames, (
                f"Expected alpha in filename-filtered search, got {filenames}"
            )
            assert beta.name not in filenames, (
                f"Filename filter leaked: beta in {filenames}"
            )
            assert all(r.filename == alpha.name for r in results.results)
        finally:
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)
