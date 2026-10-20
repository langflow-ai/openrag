"""
Unit tests for how services/search_service.py applies the score threshold.

OpenSearch DLS adds its role query to every user-scoped search as a
constant-score clause, so a top-level min_score is met by every visible hit.
The threshold must therefore sit inside the query, on the hybrid score.

Verifies:
- a positive threshold wraps the hybrid query in function_score.min_score
- no top-level min_score is sent
- threshold 0 and wildcard queries are not wrapped
- the num_candidates retry still strips num_candidates inside the wrapper
"""

from types import SimpleNamespace

import pytest
from opensearchpy.exceptions import RequestError

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from services.search_service import SearchService


class _OpenSearch:
    """Minimal OpenSearch stub that records every non-agg search body."""

    def __init__(self, reject_num_candidates: bool = False):
        self.bodies: list[dict] = []
        self._reject_num_candidates = reject_num_candidates

    async def search(self, *, index, body, params):
        # Agg-only probes (embedding space detection, wildcard facets)
        if body.get("size") == 0:
            return {
                "aggregations": {
                    "embedding_spaces": {"buckets": []},
                    "legacy_embedding_models": {"buckets": []},
                }
            }
        self.bodies.append(body)
        if self._reject_num_candidates and len(self.bodies) == 1:
            raise RequestError(
                400,
                "x_content_parse_exception",
                {"error": {"root_cause": [{"reason": "[knn] unknown field [num_candidates]"}]}},
            )
        return {"hits": {"hits": []}, "aggregations": {}}


def _make_service(opensearch: _OpenSearch, monkeypatch) -> SearchService:
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None

    async def _no_embed(body, **_kwargs):
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", _no_embed)
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


def _set_context(score_threshold: float) -> None:
    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(100)
    set_score_threshold(score_threshold)


def _knn_params(query: dict) -> list[dict]:
    hybrid = query.get("function_score", {}).get("query", query)
    knn_queries = hybrid["bool"]["should"][0]["dis_max"]["queries"]
    return [params for knn in knn_queries for params in knn["knn"].values()]


@pytest.mark.asyncio
async def test_positive_threshold_applies_inside_the_query(monkeypatch):
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    function_score = body["query"]["function_score"]
    assert function_score["min_score"] == 1.0
    assert "functions" not in function_score
    assert function_score["query"]["bool"]["minimum_should_match"] == 1


@pytest.mark.asyncio
async def test_zero_threshold_leaves_the_query_unwrapped(monkeypatch):
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert "function_score" not in body["query"]
    assert "bool" in body["query"]


@pytest.mark.asyncio
async def test_wildcard_query_ignores_the_threshold(monkeypatch):
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("*")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert body["query"] == {"match_all": {}}


@pytest.mark.asyncio
async def test_num_candidates_retry_keeps_the_threshold(monkeypatch):
    os_client = _OpenSearch(reject_num_candidates=True)
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("MCP")

    first, retry = os_client.bodies
    assert all("num_candidates" in params for params in _knn_params(first["query"]))
    assert all("num_candidates" not in params for params in _knn_params(retry["query"]))
    assert retry["query"]["function_score"]["min_score"] == 1.0
    assert "min_score" not in retry
