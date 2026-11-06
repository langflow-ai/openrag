"""/v1/search tells the search trace which saved knowledge filter it applied."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.v1 import search as v1_search
from observability.tracing import current_trace_context


def _service(seen: list):
    async def search(query, **_kwargs):
        seen.append(dict(current_trace_context()))
        return {"results": []}

    return SimpleNamespace(search=search)


@pytest.mark.asyncio
async def test_the_applied_filter_id_is_in_the_search_trace_context(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        v1_search,
        "resolve_filter_id",
        AsyncMock(return_value={"filters": {}, "limit": 10, "score_threshold": 0}),
    )
    user = SimpleNamespace(user_id="u1", jwt_token=None)

    await v1_search.search_endpoint(
        v1_search.SearchV1Body(query="q", filter_id="filter-1"),
        search_service=_service(seen),
        user=user,
        knowledge_filter_service=None,
    )

    assert seen[0]["attributes"] == {"openrag.search.filter_id": "filter-1"}


@pytest.mark.asyncio
async def test_no_filter_id_adds_nothing():
    seen: list = []
    user = SimpleNamespace(user_id="u1", jwt_token=None)

    await v1_search.search_endpoint(
        v1_search.SearchV1Body(query="q"),
        search_service=_service(seen),
        user=user,
        knowledge_filter_service=None,
    )

    assert "attributes" not in seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters",
    [
        {"created_after": "not-a-date"},
        {"created_before": 20261010},
        {"created_after": "2026-10-10T00:00:00Z", "created_before": "2026-10-07T00:00:00Z"},
    ],
)
async def test_v1_search_rejects_invalid_date_bounds(filters):
    from fastapi import HTTPException

    seen: list = []
    user = SimpleNamespace(user_id="u1", jwt_token=None)

    with pytest.raises(HTTPException) as exc:
        await v1_search.search_endpoint(
            v1_search.SearchV1Body(query="q", filters=filters),
            search_service=_service(seen),
            user=user,
            knowledge_filter_service=None,
        )

    assert exc.value.status_code == 422
    assert seen == []


@pytest.mark.asyncio
async def test_v1_search_rejects_invalid_bounds_from_a_saved_filter(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        v1_search,
        "resolve_filter_id",
        AsyncMock(
            return_value={
                "filters": {"created_after": "garbage"},
                "limit": 10,
                "score_threshold": 0,
            }
        ),
    )
    user = SimpleNamespace(user_id="u1", jwt_token=None)

    with pytest.raises(HTTPException) as exc:
        await v1_search.search_endpoint(
            v1_search.SearchV1Body(query="q", filter_id="filter-1"),
            search_service=_service([]),
            user=user,
            knowledge_filter_service=None,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_v1_search_accepts_valid_date_bounds():
    seen: list = []
    user = SimpleNamespace(user_id="u1", jwt_token=None)

    await v1_search.search_endpoint(
        v1_search.SearchV1Body(
            query="q",
            filters={
                "created_after": "2026-10-07T00:00:00Z",
                "created_before": "2026-10-10T23:59:59Z",
            },
        ),
        search_service=_service(seen),
        user=user,
        knowledge_filter_service=None,
    )

    assert len(seen) == 1
