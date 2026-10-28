"""Unit tests for SearchService.suggest and the embedding/space caches."""

from types import SimpleNamespace

import pytest

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from services.search_cache import clear_search_caches
from services.search_service import SearchService, _filters_to_clauses, _group_suggest_files


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_search_caches()
    yield
    clear_search_caches()


class _OpenSearch:
    """Routes the three request shapes the suggest path produces."""

    def __init__(self, tag="u1"):
        self.tag = tag
        self.keyword_calls = 0
        self.count_calls = 0
        self.space_calls = 0
        self.bodies = []

    async def search(self, *, index, body, params):
        self.bodies.append(body)
        aggs = body.get("aggs", {})
        if "candidates" in aggs:
            self.count_calls += 1
            names = [
                f["match_phrase_prefix"]["text"]["query"]
                for f in aggs["candidates"]["filters"]["filters"]
            ]
            return {
                "aggregations": {
                    "candidates": {
                        "buckets": [
                            {"doc_count": 61 if i == 0 else 0, "files": {"value": 2}}
                            for i, _ in enumerate(names)
                        ]
                    }
                }
            }
        if body.get("size") == 0 and "embedding_spaces" in aggs:
            self.space_calls += 1
            return {
                "aggregations": {
                    "embedding_spaces": {
                        "buckets": [{"key": {"space_id": "openai:te3"}, "doc_count": 1}]
                    }
                }
            }
        if body.get("size") == 0 and "legacy_embedding_models" in aggs:
            return {"aggregations": {"legacy_embedding_models": {"buckets": []}}}
        self.keyword_calls += 1
        return {
            "hits": {
                "hits": [
                    {
                        "_id": f"{self.tag}-1",
                        "_source": {
                            "filename": f"{self.tag}-docling.pdf",
                            "mimetype": "application/pdf",
                            "connector_type": "local",
                            "text": "Run docling serve to start. Docling converts files.",
                        },
                        "highlight": {"text": ["Run <mark>docling</mark> serve to start"]},
                    },
                    {
                        "_id": f"{self.tag}-2",
                        "_source": {
                            "filename": f"{self.tag}-notes.md",
                            "mimetype": "text/markdown",
                            "connector_type": "local",
                            "text": "Unrelated notes about lunch plans for the team offsite.",
                        },
                    },
                ]
            },
            "aggregations": {},
        }


def _service(opensearch_by_user, monkeypatch, embed_calls=None):
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt: opensearch_by_user[user_id]
    )
    service.models_service = None

    async def create_embedding(body, *, interactive=False):
        if embed_calls is not None:
            embed_calls.append(body["input"][0])
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", create_embedding)
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.search_service.get_embedding_model", lambda: "te3")
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_provider="openai", legacy_embedding_provider_map={}
            ),
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=None)),
        ),
    )
    return service


@pytest.mark.asyncio
async def test_keyword_phase_returns_suggestions_files_and_top_previews(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    result = await service.suggest("docl", user_id="u1")

    assert result["phase"] == "keyword"
    assert result["suggestions"][0] == {"text": "docling", "files": 2, "chunks": 61}
    assert [f["filename"] for f in result["files"]] == ["u1-docling.pdf", "u1-notes.md"]
    first = result["files"][0]["preview"]
    assert first["kind"] == "keyword"
    assert "<mark>docling</mark>" in first["text"]
    # No keyword match and semantic is off: no guessed preview.
    assert result["files"][1]["preview"] is None


@pytest.mark.asyncio
async def test_keyword_phase_never_embeds(monkeypatch):
    embed_calls = []
    service = _service({"u1": _OpenSearch()}, monkeypatch, embed_calls)

    await service.suggest("docling", user_id="u1")

    assert embed_calls == []


@pytest.mark.asyncio
async def test_repeat_request_is_served_from_cache(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    first = await service.suggest("Docling", user_id="u1")
    second = await service.suggest("  docling ", user_id="u1")

    assert first == second
    assert opensearch.keyword_calls == 1
    assert opensearch.count_calls == 1


@pytest.mark.asyncio
async def test_cache_is_isolated_between_users(monkeypatch):
    u1, u2 = _OpenSearch("u1"), _OpenSearch("u2")
    service = _service({"u1": u1, "u2": u2}, monkeypatch)

    r1 = await service.suggest("docling", user_id="u1")
    r2 = await service.suggest("docling", user_id="u2")

    assert r1["files"][0]["filename"] == "u1-docling.pdf"
    assert r2["files"][0]["filename"] == "u2-docling.pdf"
    assert u2.keyword_calls == 1


@pytest.mark.asyncio
async def test_semantic_phase_embeds_once_and_upgrades_keyword_cache(monkeypatch):
    embed_calls = []
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch, embed_calls)
    set_auth_context("u1", "jwt")
    set_search_filters({})
    set_search_limit(10)
    set_score_threshold(0)

    semantic = await service.suggest("docling", user_id="u1", jwt_token="jwt", semantic=True)
    assert semantic["phase"] == "semantic"
    assert embed_calls == ["docling"]
    # With semantic on, the unmatched file gets a best-sentence preview.
    notes = next(f for f in semantic["files"] if f["filename"] == "u1-notes.md")
    assert notes["preview"]["kind"] == "semantic"

    keyword_calls_before = opensearch.keyword_calls
    again = await service.suggest("docling", user_id="u1", jwt_token="jwt", semantic=False)
    assert again is semantic
    assert opensearch.keyword_calls == keyword_calls_before


@pytest.mark.asyncio
async def test_search_tool_reuses_cached_embedding_and_spaces(monkeypatch):
    embed_calls = []
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch, embed_calls)
    set_auth_context("u1", "jwt")
    set_search_filters({})
    set_search_limit(10)
    set_score_threshold(0)

    await service.search_tool("needle")
    await service.search_tool("needle")
    await service.search_tool("other")

    assert embed_calls == ["needle", "other"]
    assert opensearch.space_calls == 1


@pytest.mark.asyncio
async def test_too_short_query_returns_empty_without_touching_opensearch(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    result = await service.suggest("d", user_id="u1")

    assert result["suggestions"] == [] and result["files"] == []
    assert opensearch.bodies == []


@pytest.mark.asyncio
async def test_degraded_semantic_response_is_not_cached(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)
    calls = 0

    async def degraded_search(query, **kwargs):
        nonlocal calls
        calls += 1
        return {"results": [], "warnings": [{"code": "embedding_unavailable"}]}

    monkeypatch.setattr(service, "search", degraded_search)

    await service.suggest("docling", user_id="u1", semantic=True)
    await service.suggest("docling", user_id="u1", semantic=True)

    assert calls == 2


@pytest.mark.asyncio
async def test_cache_is_keyed_by_score_threshold(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)
    thresholds = []

    async def fake_search(query, **kwargs):
        thresholds.append(kwargs["score_threshold"])
        return {"results": []}

    monkeypatch.setattr(service, "search", fake_search)

    await service.suggest("docling", user_id="u1", semantic=True, score_threshold=1.0)
    await service.suggest("docling", user_id="u1", semantic=True, score_threshold=2.0)
    await service.suggest("docling", user_id="u1", semantic=True, score_threshold=2.0)

    assert thresholds == [1.0, 2.0]


@pytest.mark.asyncio
async def test_semantic_suggest_tags_its_search_trace_as_suggest(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)
    sources = []

    async def fake_search_tool(query, embedding_model=None, *, source):
        sources.append(source)
        return {"results": []}

    monkeypatch.setattr(service, "search_tool", fake_search_tool)

    await service.suggest("docling", user_id="u1", semantic=True)

    assert sources == ["suggest"]


@pytest.mark.asyncio
async def test_search_defaults_its_trace_source_to_api(monkeypatch):
    service = _service({"u1": _OpenSearch()}, monkeypatch)
    sources = []

    async def fake_search_tool(query, embedding_model=None, *, source):
        sources.append(source)
        return {"results": []}

    monkeypatch.setattr(service, "search_tool", fake_search_tool)

    await service.search("docling", user_id="u1")

    assert sources == ["api"]


@pytest.mark.asyncio
async def test_keyword_request_is_not_answered_by_other_threshold_semantic_cache(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    async def fake_search(query, **kwargs):
        return {"results": []}

    monkeypatch.setattr(service, "search", fake_search)

    await service.suggest("docling", user_id="u1", semantic=True, score_threshold=1.0)
    await service.suggest("docling", user_id="u1", semantic=False, score_threshold=2.0)

    assert opensearch.keyword_calls == 1


@pytest.mark.asyncio
async def test_semantic_suggest_skips_keyword_query_when_threshold_is_set(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    async def fake_search(query, **kwargs):
        return {"results": []}

    monkeypatch.setattr(service, "search", fake_search)

    await service.suggest("docling", user_id="u1", semantic=True, score_threshold=1.0)
    assert opensearch.keyword_calls == 0

    await service.suggest("other", user_id="u1", semantic=True)
    assert opensearch.keyword_calls == 1


@pytest.mark.asyncio
async def test_suggest_without_jwt_still_resolves_the_user_client(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)

    result = await service.suggest("docling", user_id="u1", jwt_token=None)

    assert result["files"]
    assert opensearch.keyword_calls == 1


@pytest.mark.asyncio
async def test_semantic_error_payload_is_returned_and_not_cached(monkeypatch):
    opensearch = _OpenSearch()
    service = _service({"u1": opensearch}, monkeypatch)
    calls = 0

    async def failing_search(query, **kwargs):
        nonlocal calls
        calls += 1
        return {"error": "Authentication required"}

    monkeypatch.setattr(service, "search", failing_search)

    first = await service.suggest("docling", user_id="u1", semantic=True)
    await service.suggest("docling", user_id="u1", semantic=True)

    assert first == {"error": "Authentication required"}
    assert calls == 2


def test_filters_to_clauses_allowlists_fields():
    clauses = _filters_to_clauses(
        {
            "data_sources": ["a.pdf"],
            "owners": ["x", "y"],
            "connector_types": [],
            "_index": ["evil"],
            "document_types": "not-a-list",
        }
    )
    assert {"term": {"filename": "a.pdf"}} in clauses
    assert {"terms": {"owner": ["x", "y"]}} in clauses
    assert {"term": {"connector_type": "__IMPOSSIBLE_VALUE__"}} in clauses
    assert len(clauses) == 3


def test_group_suggest_files_limits_rows_and_previews():
    chunks = [
        {
            "filename": f"f{i}.txt",
            "text": "docling text here",
            "highlights": ["<mark>docling</mark> text"],
        }
        for i in range(8)
    ]
    files = _group_suggest_files(chunks, "docling", allow_semantic=False)
    assert len(files) == 5
    assert [f["preview"] is not None for f in files] == [True, True, True, False, False]
