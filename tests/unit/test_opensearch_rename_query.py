"""Unit tests for OpenSearch rename query helper."""

from utils.opensearch_queries import (
    build_document_id_match_query,
    build_document_id_not_matching_filenames_query,
    build_rename_collision_query,
    build_rename_match_query,
)


def test_rename_query_filename_should_no_owner_term():
    q = build_rename_match_query("user-1", ["a.txt", "a.md"], None)
    assert q == {
        "bool": {
            "must": [
                {
                    "bool": {
                        "should": [
                            {"term": {"filename": "a.txt"}},
                            {"term": {"filename": "a.md"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            ]
        }
    }


def test_rename_query_anonymous_same_shape():
    q = build_rename_match_query("anonymous", ["b.pdf"], None)
    assert q["bool"]["must"] == [
        {
            "bool": {
                "should": [{"term": {"filename": "b.pdf"}}],
                "minimum_should_match": 1,
            }
        }
    ]


def test_rename_query_adds_document_id():
    q = build_rename_match_query("u", ["c.txt"], "doc-xyz")
    assert {"term": {"document_id": "doc-xyz"}} in q["bool"]["must"]


def test_rename_collision_query_exclude_document_id_no_owner():
    q = build_rename_collision_query("user-1", ["x.txt", "x.md"], "doc-1")
    assert q == {
        "bool": {
            "must": [
                {
                    "bool": {
                        "should": [
                            {"term": {"filename": "x.txt"}},
                            {"term": {"filename": "x.md"}},
                        ],
                        "minimum_should_match": 1,
                    },
                }
            ],
            "must_not": [{"term": {"document_id": "doc-1"}}],
        }
    }


def test_rename_collision_query_anonymous_no_owner_term():
    q = build_rename_collision_query("anonymous", ["y.pdf"], None)
    assert q["bool"]["must"] == [
        {
            "bool": {
                "should": [{"term": {"filename": "y.pdf"}}],
                "minimum_should_match": 1,
            }
        }
    ]
    assert "must_not" not in q["bool"]


def test_document_id_match_query_no_owner():
    q = build_document_id_match_query("user-1", "doc-1")
    assert q == {
        "bool": {
            "must": [
                {"term": {"document_id": "doc-1"}},
            ]
        }
    }


def test_document_id_not_matching_filenames_must_not():
    q = build_document_id_not_matching_filenames_query(
        "user-1", "doc-1", ["out.pdf", "out.md"]
    )
    assert q["bool"]["must"] == [
        {"term": {"document_id": "doc-1"}},
    ]
    assert "must_not" in q["bool"]
    assert len(q["bool"]["must_not"]) == 1
