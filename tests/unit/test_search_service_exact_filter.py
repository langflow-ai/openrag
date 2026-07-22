"""
Unit tests for the exact-match file filter in services/search_service.py.

Regression: token-like queries (e.g. "chunk_overlap", "v1.2", "SKU-1234")
must not zero out ranked hybrid results when no file contains the query
verbatim.
"""

import pytest

from services.search_service import _apply_exact_match_file_filter


def _chunk(filename: str, text: str, **extra) -> dict:
    return {
        "filename": filename,
        "text": text,
        "mimetype": "application/pdf",
        "owner": "user-1",
        "connector_type": "local",
        "embedding_model": "text-embedding-3-small",
        **extra,
    }


BASE_AGGS = {
    "data_sources": {"buckets": [{"key": "report.pdf", "doc_count": 2}]},
    "document_types": {"buckets": [{"key": "application/pdf", "doc_count": 2}]},
}


@pytest.mark.parametrize("query", ["chunk_overlap", "v1.2", "SKU-1234"])
def test_token_like_query_without_exact_match_keeps_hybrid_results(query):
    """Token-like queries must not clear ranked hits when nothing matches verbatim."""
    chunks = [
        _chunk("report.pdf", "Discussion of chunking strategies and overlap."),
        _chunk("notes.md", "Semantic search configuration notes."),
    ]

    filtered, aggs = _apply_exact_match_file_filter(
        query, chunks, BASE_AGGS, is_wildcard_match_all=False
    )

    assert filtered == chunks
    assert aggs == BASE_AGGS


def test_verbatim_match_in_text_restricts_to_matching_files():
    chunks = [
        _chunk("config-guide.pdf", "Set chunk_overlap to 200 for best results."),
        _chunk("unrelated.pdf", "Quarterly financial summary."),
    ]

    filtered, aggs = _apply_exact_match_file_filter(
        "chunk_overlap", chunks, BASE_AGGS, is_wildcard_match_all=False
    )

    assert [c["filename"] for c in filtered] == ["config-guide.pdf"]
    assert aggs["data_sources"]["buckets"] == [{"key": "config-guide.pdf", "doc_count": 1}]


def test_verbatim_match_in_filename_restricts_to_matching_files():
    chunks = [
        _chunk("SKU-1234-spec.pdf", "Product specification."),
        _chunk("other.pdf", "Different product."),
    ]

    filtered, _ = _apply_exact_match_file_filter(
        "SKU-1234", chunks, BASE_AGGS, is_wildcard_match_all=False
    )

    assert [c["filename"] for c in filtered] == ["SKU-1234-spec.pdf"]


def test_multiword_prose_query_is_not_narrowed():
    """Ordinary prose queries keep hybrid-ranked results even when one chunk
    happens to contain the phrase verbatim — narrowing is for token-like
    lookups only."""
    chunks = [
        _chunk("guide.pdf", "The quarterly revenue summary is attached below."),
        _chunk("other.pdf", "Revenue grew on strong quarterly performance."),
    ]

    filtered, aggs = _apply_exact_match_file_filter(
        "quarterly revenue summary", chunks, BASE_AGGS, is_wildcard_match_all=False
    )

    assert filtered == chunks
    assert aggs == BASE_AGGS


def test_wildcard_and_short_queries_are_untouched():
    chunks = [_chunk("report.pdf", "text"), _chunk("notes.md", "more text")]

    for query, wildcard in [("*", True), ("ab", False), ("", False)]:
        filtered, aggs = _apply_exact_match_file_filter(
            query, chunks, BASE_AGGS, is_wildcard_match_all=wildcard
        )
        assert filtered == chunks
        assert aggs == BASE_AGGS
