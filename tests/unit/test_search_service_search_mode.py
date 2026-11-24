"""
Unit tests for the diagnostic search modes in services/search_service.py.

``hybrid`` (the default) runs both halves of the query. ``vector`` and
``keyword`` run one half each, keeping the boost it has inside hybrid search, so
a caller can see which half finds or loses a document.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.v1 import search as v1_search
from auth_context import (
    get_search_mode,
    set_auth_context,
    set_score_threshold,
    set_search_filters,
    set_search_limit,
    set_search_mode,
    set_search_result_mode,
)
from services.search_service import SearchService


class _OpenSearch:
    """Minimal OpenSearch stub that records every non-agg search body."""

    def __init__(self):
        self.bodies: list[dict] = []

    async def search(self, *, index, body, params):
        if body.get("size") == 0:  # embedding space detection
            return {
                "aggregations": {
                    "embedding_spaces": {"buckets": []},
                    "legacy_embedding_models": {"buckets": []},
                }
            }
        self.bodies.append(body)
        return {"hits": {"hits": []}, "aggregations": {}}


def _make_service(opensearch: _OpenSearch, monkeypatch, embed_calls: list) -> SearchService:
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None

    async def _embed(body, **_kwargs):
        embed_calls.append(body)
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", _embed)
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.search_service.get_embedding_model", lambda: "text-embedding-3-small"
    )
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(embedding_provider="openai"),
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=None)),
        ),
    )
    monkeypatch.setattr(
        "services.search_service.get_declared_default_embedding_model",
        lambda _: "text-embedding-3-small",
    )
    return service


def _set_context(search_mode: str, score_threshold: float = 0) -> None:
    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(50)
    set_score_threshold(score_threshold)
    set_search_result_mode("chunks")
    set_search_mode(search_mode)


def _should(body: dict) -> list[dict]:
    query = body["query"]
    return query.get("function_score", {}).get("query", query)["bool"]["should"]


def _clause_types(body: dict) -> list[str]:
    return [next(iter(clause)) for clause in _should(body)]


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    set_search_mode("hybrid")


@pytest.mark.asyncio
async def test_hybrid_runs_both_halves(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)
    _set_context("hybrid")

    await service.search_tool("rotate a key")

    should = _should(os_client.bodies[-1])
    assert _clause_types(os_client.bodies[-1]) == ["dis_max", "multi_match", "match_phrase_prefix"]
    assert should[0]["dis_max"]["boost"] == 0.7
    assert should[1]["multi_match"]["boost"] == 0.3
    assert calls, "hybrid search embeds the query"


@pytest.mark.asyncio
async def test_vector_mode_runs_only_the_knn_half_at_its_hybrid_boost(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)
    _set_context("vector")

    await service.search_tool("rotate a key")

    should = _should(os_client.bodies[-1])
    assert _clause_types(os_client.bodies[-1]) == ["dis_max"]
    assert should[0]["dis_max"]["boost"] == 0.7


@pytest.mark.asyncio
async def test_keyword_mode_runs_only_the_keyword_half_and_never_embeds(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)
    _set_context("keyword")

    await service.search_tool("rotate a key")

    should = _should(os_client.bodies[-1])
    assert _clause_types(os_client.bodies[-1]) == ["multi_match", "match_phrase_prefix"]
    # The hybrid share, not the 1.0 used when embeddings fail in hybrid mode.
    assert should[0]["multi_match"]["boost"] == 0.3
    assert calls == []


@pytest.mark.asyncio
async def test_keyword_mode_still_applies_filters_and_the_score_threshold(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)
    _set_context("keyword", score_threshold=0.5)
    set_search_filters({"data_sources": ["a.md"]})

    await service.search_tool("rotate a key")

    body = os_client.bodies[-1]
    assert body["query"]["function_score"]["min_score"] == 0.5
    assert body["query"]["function_score"]["query"]["bool"]["filter"]


@pytest.mark.asyncio
async def test_vector_mode_without_an_embedding_returns_nothing_instead_of_keywords(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)

    async def _fail(body, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("services.search_service.gateway_embeddings", _fail)
    monkeypatch.setattr("services.search_service.MAX_EMBED_RETRIES", 1)
    _set_context("vector")

    response = await service.search_tool("rotate a key")

    assert response["results"] == []
    assert response["warnings"][0]["code"] == "vector_search_unavailable"
    assert os_client.bodies == [], "no keyword search is sent in its place"


@pytest.mark.asyncio
async def test_search_sets_the_mode_for_one_call_and_restores_it(monkeypatch):
    os_client, calls = _OpenSearch(), []
    service = _make_service(os_client, monkeypatch, calls)
    seen: list[str] = []
    original = service.search_tool

    async def _spy(query, **kwargs):
        seen.append(get_search_mode())
        return await original(query, **kwargs)

    service.search_tool = _spy
    set_search_mode("hybrid")

    await service.search("rotate a key", user_id="user-1", search_mode="keyword")

    assert seen == ["keyword"]
    assert get_search_mode() == "hybrid"


@pytest.mark.asyncio
async def test_search_rejects_an_unknown_mode(monkeypatch):
    service = _make_service(_OpenSearch(), monkeypatch, [])
    with pytest.raises(ValueError, match="search_mode"):
        await service.search("q", user_id="user-1", search_mode="bm25")


@pytest.mark.asyncio
async def test_v1_search_passes_the_mode_through():
    received: list[dict] = []

    async def _search(query, **kwargs):
        received.append(kwargs)
        return {"results": []}

    await v1_search.search_endpoint(
        v1_search.SearchV1Body(query="q", search_mode="vector"),
        search_service=SimpleNamespace(search=_search),
        user=SimpleNamespace(user_id="u1", jwt_token=None),
        knowledge_filter_service=None,
    )
    await v1_search.search_endpoint(
        v1_search.SearchV1Body(query="q"),
        search_service=SimpleNamespace(search=_search),
        user=SimpleNamespace(user_id="u1", jwt_token=None),
        knowledge_filter_service=None,
    )

    assert [call["search_mode"] for call in received] == ["vector", "hybrid"]


def test_v1_search_rejects_an_unknown_mode():
    with pytest.raises(ValidationError):
        v1_search.SearchV1Body(query="q", search_mode="bm25")
