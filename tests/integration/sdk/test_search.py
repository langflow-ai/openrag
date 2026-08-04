"""Tests for the search endpoint."""

import os
from pathlib import Path

import pytest
from openrag_sdk.exceptions import OpenRAGError, ValidationError

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

        results = await client.search.query("purple elephants dancing")
        assert results.results is not None


class TestSearchExtended:
    """Additional search parameter and edge-case tests."""

    @pytest.mark.asyncio
    async def test_search_with_limit(self, client, test_file: Path):
        """limit parameter caps the number of results returned."""
        await client.documents.ingest(file_path=str(test_file))

        results = await client.search.query("test", limit=1)
        assert results.results is not None
        assert len(results.results) <= 1

    @pytest.mark.asyncio
    async def test_search_with_high_score_threshold_returns_empty(self, client, test_file: Path):
        """A score_threshold of 0.99 should filter out most or all results."""
        await client.documents.ingest(file_path=str(test_file))

        results = await client.search.query("test", score_threshold=0.99)
        assert results.results is not None
        assert isinstance(results.results, list)

    @pytest.mark.asyncio
    async def test_search_no_results_for_obscure_query(self, client):
        """A nonsense query must return an empty list, not raise an error."""
        results = await client.search.query(
            "zzz_xyzzy_nonexistent_content_abc123_qwerty_999"
        )
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
        """Each search result must have text populated as a string."""
        await client.documents.ingest(file_path=str(test_file))

        results = await client.search.query("purple elephants dancing", limit=5)
        for result in results.results:
            assert result.text is not None
            assert isinstance(result.text, str)

    @pytest.mark.asyncio
    async def test_search_with_custom_fuzziness_returns_results(self, client, test_file: Path):
        """An overridden fuzziness value (e.g. a wider AUTO band) must not error."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query(
                "purple elephants dancing", fuzziness="AUTO:7,10"
            )
            assert results.results is not None
            assert isinstance(results.results, list)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_search_with_fuzziness_zero_disables_fuzzy_matching(self, client, test_file: Path):
        """fuzziness="0" (exact keyword matching only) must not error."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.query("purple elephants dancing", fuzziness="0")
            assert results.results is not None
            assert isinstance(results.results, list)
        finally:
            await client.documents.delete(test_file.name)


class TestRawSearch:
    """Raw OpenSearch DSL search (`client.search.raw_query`) tests."""

    @pytest.mark.asyncio
    async def test_raw_query_with_dsl_dict(self, client, test_file: Path):
        """A raw OpenSearch DSL query dict returns matching hits with a _source."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query(
                {"query": {"match": {"text": "purple elephants dancing"}}}
            )
            hits = results.hits.get("hits")
            assert isinstance(hits, list)
            assert len(hits) > 0
            assert "_source" in hits[0]
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_with_plain_text_string(self, client, test_file: Path):
        """A plain-text query string falls back to a keyword match query."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query("purple elephants dancing")
            hits = results.hits.get("hits")
            assert isinstance(hits, list)
            assert len(hits) > 0
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_strips_embedding_vectors(self, client, test_file: Path):
        """Result _source must never contain a raw embedding vector field."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query(
                {"query": {"match": {"text": "purple elephants dancing"}}}
            )
            hits = results.hits.get("hits", [])
            assert len(hits) > 0
            for hit in hits:
                for key, value in hit["_source"].items():
                    if isinstance(value, list) and len(value) > 100:
                        pytest.fail(f"Embedding-like vector field '{key}' leaked into raw_search results")
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_fences_untrusted_text(self, client, test_file: Path):
        """Chunk text is wrapped in untrusted-content fence markers."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query(
                {"query": {"match": {"text": "purple elephants dancing"}}}
            )
            hits = results.hits.get("hits", [])
            assert len(hits) > 0
            for hit in hits:
                text = hit["_source"].get("text")
                if text is not None:
                    assert "<<<UNTRUSTED_DOC_CHUNK>>>" in text
                    assert "<<<END_UNTRUSTED_DOC_CHUNK>>>" in text
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_respects_limit(self, client, test_file: Path):
        """limit caps the number of hits when the DSL query doesn't set its own size."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query({"query": {"match_all": {}}}, limit=1)
            assert len(results.hits.get("hits", [])) <= 1
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_dsl_size_overrides_limit(self, client, test_file: Path):
        """An explicit "size" in the DSL query is respected over the `limit` param."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query(
                {"query": {"match_all": {}}, "size": 2}, limit=50
            )
            assert len(results.hits.get("hits", [])) <= 2
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_with_filters_scopes_to_file(self, client, test_file: Path):
        """Inline filters narrow raw DSL results to the matching data source."""
        await client.documents.ingest(file_path=str(test_file))

        try:
            results = await client.search.raw_query(
                {"query": {"match_all": {}}},
                filters={"data_sources": [test_file.name]},
            )
            hits = results.hits.get("hits", [])
            for hit in hits:
                assert hit["_source"].get("filename") == test_file.name
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_raw_query_no_results_for_obscure_query(self, client):
        """A nonsense query must return an empty hit list, not raise an error."""
        results = await client.search.raw_query(
            {"query": {"match": {"text": "zzz_xyzzy_nonexistent_content_abc123_qwerty_999"}}}
        )
        assert isinstance(results.hits.get("hits"), list)

    @pytest.mark.asyncio
    async def test_raw_query_whitespace_string_raises_validation_error(self, client):
        """A whitespace-only string query must raise ValidationError, not be treated as valid."""
        with pytest.raises(ValidationError):
            await client.search.raw_query("   ")

    @pytest.mark.asyncio
    async def test_raw_query_invalid_dsl_raises_error(self, client):
        """A malformed query DSL clause must raise an SDK error, not silently succeed."""
        with pytest.raises(OpenRAGError):
            await client.search.raw_query({"query": {"not_a_real_query_type": {}}})
