from typing import Any

from pydantic import BaseModel

from api.v1._filter_resolution import merge_filter_overrides


class _RequestBody(BaseModel):
    filters: dict[str, Any] | None = None
    limit: int = 10
    score_threshold: float = 0


def test_merge_filter_overrides_uses_resolved_values_when_fields_absent():
    resolved = {
        "filters": {"data_sources": ["alpha.md"], "owners": ["alice"]},
        "limit": 5,
        "score_threshold": 0.4,
    }

    filters, limit, score_threshold = merge_filter_overrides(resolved, _RequestBody())

    assert filters == resolved["filters"]
    assert limit == 5
    assert score_threshold == 0.4


def test_merge_filter_overrides_respects_explicit_defaults_and_empty_filters():
    resolved = {
        "filters": {"data_sources": ["alpha.md"]},
        "limit": 5,
        "score_threshold": 0.4,
    }
    body = _RequestBody(filters={}, limit=10, score_threshold=0)

    filters, limit, score_threshold = merge_filter_overrides(resolved, body)

    assert filters == {}
    assert limit == 10
    assert score_threshold == 0


def test_merge_filter_overrides_merges_partial_inline_filters_per_field():
    resolved = {
        "filters": {"data_sources": ["alpha.md"], "owners": ["alice"]},
        "limit": 5,
        "score_threshold": 0.4,
    }
    body = _RequestBody(filters={"data_sources": ["beta.md"]})

    filters, limit, score_threshold = merge_filter_overrides(resolved, body)

    assert filters == {"data_sources": ["beta.md"], "owners": ["alice"]}
    assert limit == 5
    assert score_threshold == 0.4
