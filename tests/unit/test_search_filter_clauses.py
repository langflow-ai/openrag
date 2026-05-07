"""Tests for rename-aware source filters (document_id + filename)."""

from utils.search_filter_clauses import (
    build_data_source_opensearch_clause,
    build_user_filter_clauses,
)


def test_wildcard_data_sources_no_clause():
    assert build_data_source_opensearch_clause(
        {"data_sources": ["*"], "data_source_refs": []}
    ) is None


def test_refs_apply_despite_wildcard_data_sources():
    c = build_data_source_opensearch_clause(
        {
            "data_sources": ["*"],
            "data_source_refs": [{"filename": "a.pdf", "document_id": "u1"}],
        }
    )
    assert c is not None
    assert "bool" in c


def test_refs_apply_when_data_sources_empty():
    c = build_data_source_opensearch_clause(
        {
            "data_sources": [],
            "data_source_refs": [{"filename": "only.pdf", "document_id": None}],
        }
    )
    assert c == {"term": {"filename": "only.pdf"}}


def test_refs_document_id_only():
    c = build_data_source_opensearch_clause(
        {
            "data_sources": ["*"],
            "data_source_refs": [{"filename": "", "document_id": "doc-1"}],
        }
    )
    assert c == {"term": {"document_id": "doc-1"}}


def test_legacy_filenames_only():
    c = build_data_source_opensearch_clause(
        {"data_sources": ["a.pdf", "b.pdf"], "data_source_refs": []}
    )
    assert c == {"terms": {"filename": ["a.pdf", "b.pdf"]}}


def test_refs_or_filename_or_document_id():
    c = build_data_source_opensearch_clause(
        {
            "data_sources": ["docuuid"],
            "data_source_refs": [
                {
                    "filename": "old.pdf",
                    "document_id": "docuuid",
                }
            ],
        }
    )
    assert c is not None
    assert "bool" in c
    inner_should = c["bool"]["should"]
    assert len(inner_should) == 2
    fields = {list(x["term"].keys())[0] for x in inner_should}
    assert fields == {"filename", "document_id"}


def test_build_user_skips_internal_keys():
    clauses = build_user_filter_clauses(
        {
            "data_sources": ["x.pdf"],
            "data_source_refs": [{"filename": "x.pdf", "document_id": None}],
            "document_types": ["application/pdf"],
        }
    )
    assert len(clauses) >= 2
