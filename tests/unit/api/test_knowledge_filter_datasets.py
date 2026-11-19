"""Knowledge filters keep their `datasets` selection through save and resolve."""

import json

import pytest

from api.knowledge_filter import normalize_query_data
from api.v1._filter_resolution import _strip_wildcards, merge_filter_overrides


def _norm(filters):
    return json.loads(normalize_query_data({"filters": filters}))["filters"]


def test_missing_datasets_stays_missing_meaning_all():
    assert "datasets" not in _norm({"owners": ["x"]})


def test_explicit_list_is_kept_and_deduplicated():
    assert _norm({"datasets": ["b", "a", "b"]})["datasets"] == ["b", "a"]


def test_empty_list_means_none_and_survives():
    assert _norm({"datasets": []})["datasets"] == []


@pytest.mark.parametrize("value", ["*", ["*"], ["a", "*"]])
def test_all_is_stored_the_way_other_dimensions_store_all(value):
    assert _norm({"datasets": value})["datasets"] == ["*"]


def test_normalization_is_idempotent_for_each_selection():
    for value in (["a"], [], ["*"]):
        once = normalize_query_data({"filters": {"datasets": value}})
        assert normalize_query_data(once) == once


@pytest.mark.parametrize("value", ["abc", 3, [1], [""], {"a": 1}])
def test_malformed_selection_is_rejected_not_widened(value):
    with pytest.raises(ValueError):
        normalize_query_data({"filters": {"datasets": value}})


def test_other_dimensions_are_unchanged_by_datasets():
    out = _norm({"datasets": ["a"]})
    assert out["data_sources"] == ["*"] and out["owners"] == ["*"]


def test_resolution_keeps_concrete_datasets_and_empty_list():
    assert _strip_wildcards({"datasets": ["a"]}) == {"datasets": ["a"]}
    # Unlike the other dimensions, [] is a choice and is kept.
    assert _strip_wildcards({"datasets": []}) == {"datasets": []}
    assert _strip_wildcards({"owners": []}) == {}


@pytest.mark.parametrize("value", ["*", ["*"], None])
def test_resolution_treats_star_as_all_by_dropping_the_key(value):
    assert _strip_wildcards({"datasets": value}) == {}


def test_resolution_fails_closed_on_unreadable_saved_values():
    assert _strip_wildcards({"datasets": 7}) == {"datasets": []}


class _Body:
    def __init__(self, **fields):
        self.model_fields_set = set(fields)
        self.filters = fields.get("filters")
        self.limit = 10
        self.score_threshold = 0


def test_inline_datasets_override_saved_datasets_by_presence():
    resolved = {
        "filters": {"datasets": ["saved"], "owners": ["x"]},
        "limit": 10,
        "score_threshold": 0,
    }

    filters, _, _ = merge_filter_overrides(resolved, _Body(filters={"datasets": ["inline"]}))
    assert filters == {"datasets": ["inline"], "owners": ["x"]}

    filters, _, _ = merge_filter_overrides(resolved, _Body())
    assert filters == {"datasets": ["saved"], "owners": ["x"]}

    filters, _, _ = merge_filter_overrides(resolved, _Body(filters={"datasets": []}))
    assert filters["datasets"] == []
