# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

"""Tests for the search endpoint."""

import os
from pathlib import Path

import pytest

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
        """Each search result must have text populated as a string."""
        await client.documents.ingest(file_path=str(test_file))

        results = await client.search.query("purple elephants dancing", limit=5)
        for result in results.results:
            assert result.text is not None
            assert isinstance(result.text, str)
