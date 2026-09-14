"""
Unit tests for search result highlighting in services/search_service.py.

Verifies:
- highlight block is added to search_body for normal queries
- highlight block is omitted for wildcard ("*") queries
- highlights returned by OpenSearch are surfaced on each chunk
- pure KNN hits (no keyword match) produce an empty highlights list
"""

from types import SimpleNamespace

import pytest

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from services.search_service import SearchService


def _make_hit(text: str, highlights: list[str] | None = None) -> dict:
    hit = {
        "_id": "abc123",
        "_score": 0.9,
        "_source": {
            "filename": "doc.pdf",
            "mimetype": "application/pdf",
            "page": 1,
            "text": text,
        },
    }
    if highlights is not None:
        hit["highlight"] = {"text": highlights}
    return hit


class _OpenSearch:
    """Minimal OpenSearch stub that records the last non-agg search body."""

    def __init__(self, hits: list[dict] | None = None):
        self.captured_body: dict | None = None
        self._hits = hits or []

    async def search(self, *, index, body, params):
        # Agg-only probes (embedding space detection, wildcard facets)
        if body.get("size") == 0:
            return {"aggregations": {"embedding_spaces": {"buckets": []},
                                     "legacy_embedding_models": {"buckets": []}}}
        self.captured_body = body
        return {
            "hits": {"hits": self._hits},
            "aggregations": {},
        }


def _make_service(opensearch: _OpenSearch, monkeypatch) -> SearchService:
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None

    async def _no_embed(body):
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", _no_embed)
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.search_service.get_embedding_model", lambda: "text-embedding-3-small")
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


@pytest.mark.asyncio
async def test_highlight_block_added_for_normal_query(monkeypatch):
    """search_body must include a highlight block for non-wildcard queries."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)

    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(5)
    set_score_threshold(0)

    await service.search_tool("what is chunking?")

    assert os_client.captured_body is not None
    assert "highlight" in os_client.captured_body
    hl = os_client.captured_body["highlight"]
    assert "text" in hl["fields"]
    assert hl["fields"]["text"]["pre_tags"] == ["<mark>"]
    assert hl["fields"]["text"]["post_tags"] == ["</mark>"]


@pytest.mark.asyncio
async def test_highlight_block_omitted_for_wildcard_query(monkeypatch):
    """Wildcard '*' queries must NOT include a highlight block."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)

    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(5)
    set_score_threshold(0)

    await service.search_tool("*")

    assert os_client.captured_body is not None
    assert "highlight" not in os_client.captured_body


@pytest.mark.asyncio
async def test_highlights_surfaced_on_chunk(monkeypatch):
    """Highlight fragments returned by OpenSearch appear on the chunk dict."""
    fragments = ["text with <mark>chunking</mark> strategy"]
    os_client = _OpenSearch(hits=[_make_hit("text with chunking strategy", fragments)])
    service = _make_service(os_client, monkeypatch)

    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(5)
    set_score_threshold(0)

    result = await service.search_tool("chunking")

    assert result["results"][0]["highlights"] == fragments


@pytest.mark.asyncio
async def test_highlights_empty_when_no_keyword_match(monkeypatch):
    """Pure KNN hits (no highlight key in response) produce an empty list."""
    os_client = _OpenSearch(hits=[_make_hit("some semantically relevant text")])
    service = _make_service(os_client, monkeypatch)

    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(5)
    set_score_threshold(0)

    result = await service.search_tool("relevant query")

    assert result["results"][0]["highlights"] == []
