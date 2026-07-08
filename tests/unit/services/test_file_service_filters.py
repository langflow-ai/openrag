"""Tests for FileService._build_filter_query multi-value filter support."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.file_service import FileService  # noqa: E402


def _filters(query: dict) -> list[dict]:
    return query["bool"]["filter"]


def test_no_filters_yields_empty_clauses():
    query = FileService()._build_filter_query("user-1")
    assert _filters(query) == []
    assert "must" not in query["bool"]


def test_single_value_uses_term_clause():
    query = FileService()._build_filter_query("user-1", connector_type=["s3"])
    assert _filters(query) == [{"term": {"connector_type": "s3"}}]


def test_multiple_values_use_terms_clause():
    query = FileService()._build_filter_query(
        "user-1",
        connector_type=["s3", "google_drive"],
        mimetype=["application/pdf", "text/plain"],
        owner=["alice", "bob"],
    )
    assert _filters(query) == [
        {"terms": {"connector_type": ["s3", "google_drive"]}},
        {"terms": {"mimetype": ["application/pdf", "text/plain"]}},
        {"terms": {"owner": ["alice", "bob"]}},
    ]


def test_data_source_filters_on_filename_field():
    query = FileService()._build_filter_query("user-1", data_source=["report.pdf", "notes.txt"])
    assert _filters(query) == [{"terms": {"filename": ["report.pdf", "notes.txt"]}}]


def test_plain_string_still_supported():
    query = FileService()._build_filter_query("user-1", owner="alice")
    assert _filters(query) == [{"term": {"owner": "alice"}}]


def test_search_combines_with_filters():
    query = FileService()._build_filter_query("user-1", connector_type=["s3"], search="Report")
    assert _filters(query) == [{"term": {"connector_type": "s3"}}]
    should = query["bool"]["must"][0]["bool"]["should"]
    assert {"wildcard": {"filename": {"value": "*report*"}}} in should
