import pytest

from utils.opensearch_queries import build_filter_clauses

RANGE = {
    "range": {"indexed_time": {"gte": "2026-10-07T00:00:00.000000Z", "lte": "2026-10-10T23:59:59.999Z"}}
}
DATES = {"created_after": "2026-10-07T00:00:00Z", "created_before": "2026-10-10T23:59:59.999Z"}


def test_no_filters_returns_empty():
    assert build_filter_clauses(None) == []
    assert build_filter_clauses({}) == []


def test_single_and_multiple_values():
    clauses = build_filter_clauses({"document_types": ["application/pdf"], "owners": ["a", "b"]})
    assert clauses == [
        {"term": {"mimetype": "application/pdf"}},
        {"terms": {"owner": ["a", "b"]}},
    ]


def test_empty_list_ignored_by_default():
    assert build_filter_clauses({"owners": []}) == []


def test_empty_list_matches_nothing_for_search():
    assert build_filter_clauses({"owners": []}, empty_list_matches_nothing=True) == [
        {"term": {"owner": "__IMPOSSIBLE_VALUE__"}}
    ]


def test_date_only_filter_builds_range():
    assert build_filter_clauses(dict(DATES)) == [RANGE]


def test_dates_combined_with_lists_and_not_treated_as_terms():
    clauses = build_filter_clauses({"document_types": ["application/pdf"], **DATES})
    assert clauses == [{"term": {"mimetype": "application/pdf"}}, RANGE]


def test_single_bound_and_blank_bounds():
    assert build_filter_clauses({"created_after": "2026-10-07T00:00:00Z"}) == [
        {"range": {"indexed_time": {"gte": "2026-10-07T00:00:00.000000Z"}}}
    ]
    assert build_filter_clauses({"created_after": "", "created_before": None}) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-10", "2026-10-10T00:00:00.000000Z"),
        ("2026-10-10Z", "2026-10-10T00:00:00.000000Z"),
        ("2026-10-10T10:30", "2026-10-10T10:30:00.000000Z"),
        ("2026-10-10T10:30+05:30", "2026-10-10T10:30:00.000000+05:30"),
        ("2026-10-10T10:30:15Z", "2026-10-10T10:30:15.000000Z"),
        ("2026-10-10T23:59:59.999999Z", "2026-10-10T23:59:59.999999Z"),
        ("2026-10-10T23:59:59.5", "2026-10-10T23:59:59.5"),
    ],
)
def test_date_bounds_are_sent_as_explicit_instants(raw, expected):
    from utils.opensearch_queries import build_date_range_query, normalize_date_bound

    assert normalize_date_bound(raw) == expected
    clause = build_date_range_query("indexed_time", gte=raw, lte=raw)
    assert clause == {"range": {"indexed_time": {"gte": expected, "lte": expected}}}
