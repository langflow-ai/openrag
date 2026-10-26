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
