"""SearchService.exclude_sample_data drops the bundled sample corpus.

Nudge generation uses this when no user filters are active: nudges built from
the onboarding sample docs describe the demo corpus rather than the user's own
documents. The clause is off by default so every existing caller is unaffected.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from services.search_service import SearchService

SAMPLE_DATA_CLAUSE = {"bool": {"must_not": [{"term": {"is_sample_data": "true"}}]}}


class _OpenSearch:
    """Captures the final query body; returns no hits and no aggregations."""

    def __init__(self):
        self.final_body = None

    async def search(self, *, index, body, params):
        if body.get("size") == 0:
            # Embedding-space / legacy-model detection probes.
            return {"aggregations": {}}
        self.final_body = body
        return {"hits": {"hits": []}, "aggregations": {}}


def _build_service(monkeypatch, opensearch):
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None

    async def create_embedding(body):
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", create_embedding)
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.search_service.get_embedding_model", lambda: None)
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_provider="azure",
                legacy_embedding_provider_map={},
            ),
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=None)),
        ),
    )

    set_auth_context("user-1", "jwt")
    set_search_filters({})
    set_search_limit(10)
    set_score_threshold(0)
    return service


@pytest.mark.asyncio
async def test_wildcard_excludes_sample_data_when_enabled(monkeypatch):
    """With no user filters the clause is the only thing narrowing match-all."""
    opensearch = _OpenSearch()
    service = _build_service(monkeypatch, opensearch)

    await service.search_tool("*", exclude_sample_data=True)

    assert opensearch.final_body["query"] == {"bool": {"filter": [SAMPLE_DATA_CLAUSE]}}


@pytest.mark.asyncio
async def test_wildcard_is_unchanged_when_disabled(monkeypatch):
    """Default off: /search and every existing caller keep plain match_all."""
    opensearch = _OpenSearch()
    service = _build_service(monkeypatch, opensearch)

    await service.search_tool("*")

    assert opensearch.final_body["query"] == {"match_all": {}}


@pytest.mark.asyncio
async def test_wildcard_keeps_user_filters_alongside_the_exclusion(monkeypatch):
    """The clause is appended, not substituted for the user's own filters."""
    opensearch = _OpenSearch()
    service = _build_service(monkeypatch, opensearch)
    set_search_filters({"data_sources": ["report.pdf"]})

    await service.search_tool("*", exclude_sample_data=True)

    assert opensearch.final_body["query"]["bool"]["filter"] == [
        {"term": {"filename": "report.pdf"}},
        SAMPLE_DATA_CLAUSE,
    ]


@pytest.mark.asyncio
async def test_hybrid_search_also_excludes_sample_data(monkeypatch):
    """The clause sits after the wildcard/hybrid split, so both branches get it."""
    opensearch = _OpenSearch()
    service = _build_service(monkeypatch, opensearch)

    await service.search_tool("needle", exclude_sample_data=True)

    assert SAMPLE_DATA_CLAUSE in opensearch.final_body["query"]["bool"]["filter"]


@pytest.mark.asyncio
async def test_search_forwards_the_kwarg_to_search_tool(monkeypatch):
    """The public entry point passes it through."""
    service = object.__new__(SearchService)
    service.search_tool = AsyncMock(return_value={"results": []})

    await service.search("*", user_id="u", jwt_token="j", exclude_sample_data=True)

    service.search_tool.assert_awaited_once_with(
        "*", embedding_model=None, exclude_sample_data=True
    )
