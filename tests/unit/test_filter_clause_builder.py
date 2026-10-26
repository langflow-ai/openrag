from utils.opensearch_queries import build_filter_clauses

RANGE = {
    "range": {"indexed_time": {"gte": "2026-10-07T00:00:00Z", "lte": "2026-10-10T23:59:59.999Z"}}
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
        {"range": {"indexed_time": {"gte": "2026-10-07T00:00:00Z"}}}
    ]
    assert build_filter_clauses({"created_after": "", "created_before": None}) == []
