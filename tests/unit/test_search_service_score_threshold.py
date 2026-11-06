"""
Unit tests for search query structure after the hybrid-search refactor.

With the normalization processor, OpenSearch returns scores in [0, 1] and
the frontend applies the relevance threshold via min-max normalisation.
The backend no longer wraps queries in function_score/min_score; instead it
emits a hybrid query and attaches the normalization pipeline param.
num_candidates is not sent because jvector uses k only.

Verifies:
- a positive threshold does NOT produce a top-level or inner min_score
- the hybrid query structure is used when embeddings are available
- kNN clauses never include num_candidates
- keyword-only fallback uses bool/should (no pipeline)
- wildcard queries use match_all / bool-filter (no pipeline)
- DLS wrapper causes a single-step fallback to bool/should without pipeline
- knowledge_source result mode keeps website page chunks for parent aggregation
- chunk result mode excludes website manifests (record_kind filter)
"""

from types import SimpleNamespace

import pytest
from opensearchpy.exceptions import RequestError

from auth_context import (
    set_auth_context,
    set_score_threshold,
    set_search_filters,
    set_search_limit,
    set_search_result_mode,
)
from services.search_service import SearchService
from utils.opensearch_queries import build_date_range_query


class _OpenSearch:
    """Minimal OpenSearch stub that records every non-agg search body."""

    def __init__(self, reject_num_candidates: bool = False, vector_field: dict | None = None):
        """Initialize request recording and optional rejection of the first search."""
        self.bodies: list[dict] = []
        self._reject_num_candidates = reject_num_candidates
        if vector_field is not None:
            properties = {"chunk_embedding_openai_text_embedding_3_small": vector_field}
            self.indices = SimpleNamespace(get_mapping=self._get_mapping)
            self._mapping = {"documents": {"mappings": {"properties": properties}}}

    async def _get_mapping(self, *, index):
        """Return the configured vector-field mapping."""
        return self._mapping

    async def search(self, *, index, body, params):
        """Return empty results, recording searches and optionally simulating a retry error."""
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
    """Build a search service with the supplied client and deterministic embedding stubs."""
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None

    async def _no_embed(body, **_kwargs):
        """Return a fixed query embedding without contacting an embedding provider."""
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
    """Set a test user's search context with the requested score threshold."""
    set_auth_context("user-1", None)
    set_search_filters({})
    set_search_limit(100)
    set_score_threshold(score_threshold)
    set_search_result_mode("chunks")


def _knn_params(query: dict) -> list[dict]:
    """Extract kNN parameters from the hybrid query's semantic dis_max clause."""
    knn_queries = query["hybrid"]["queries"][0]["dis_max"]["queries"]
    return [params for knn in knn_queries if "knn" in knn for params in knn["knn"].values()]


@pytest.mark.asyncio
async def test_positive_threshold_does_not_produce_min_score(monkeypatch):
    """With hybrid+normalization, score filtering is the frontend's job — no min_score in body."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert "function_score" not in body["query"]
    assert "hybrid" in body["query"]


@pytest.mark.asyncio
async def test_zero_threshold_without_default_uses_hybrid_query(monkeypatch):
    """Zero threshold still produces the hybrid query when embeddings are available."""
    monkeypatch.setattr("config.search_constants.DEFAULT_SEARCH_SCORE_THRESHOLD", 0)
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert "function_score" not in body["query"]
    assert "hybrid" in body["query"]


@pytest.mark.asyncio
async def test_zero_threshold_with_default_still_uses_hybrid_query(monkeypatch):
    """Default threshold presence does not re-introduce min_score wrapping."""
    monkeypatch.setattr("config.search_constants.DEFAULT_SEARCH_SCORE_THRESHOLD", 0.1)
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert "function_score" not in body["query"]
    assert "hybrid" in body["query"]


@pytest.mark.asyncio
async def test_explicit_threshold_does_not_wrap_hybrid_query(monkeypatch):
    """Positive explicit threshold leaves the hybrid query unwrapped."""
    monkeypatch.setattr("config.search_constants.DEFAULT_SEARCH_SCORE_THRESHOLD", 0.1)
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    assert "function_score" not in body["query"]
    assert "hybrid" in body["query"]


@pytest.mark.asyncio
async def test_wildcard_query_ignores_the_threshold(monkeypatch):
    """Verify wildcard searches use match_all even when the score threshold is positive."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(1.0)

    await service.search_tool("*")

    body = os_client.bodies[-1]
    assert "min_score" not in body
    assert body["query"]["bool"]["filter"] == [
        {"bool": {"must_not": [{"terms": {"record_kind": ["web_page_manifest", "web_source"]}}]}}
    ]


@pytest.mark.asyncio
async def test_knn_clauses_never_include_num_candidates(monkeypatch):
    """kNN queries must not include num_candidates — jvector uses k only."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    body = os_client.bodies[-1]
    knn_params = _knn_params(body["query"])
    assert knn_params, "expected at least one kNN clause"
    assert all("num_candidates" not in p for p in knn_params)
    assert all("k" in p for p in knn_params)


@pytest.mark.asyncio
async def test_knowledge_source_search_keeps_website_page_chunks_for_parent_aggregation(
    monkeypatch,
):
    """The API folds page hits into their source after SearchService ranks them."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_result_mode("knowledge_sources")

    await service.search_tool("baseball")

    filters = os_client.bodies[-1]["query"]["hybrid"].get("filter", [])
    assert not any(
        clause.get("bool", {}).get("must_not") == [{"exists": {"field": "web_page_id"}}]
        for clause in filters
    )


@pytest.mark.asyncio
async def test_chunk_search_excludes_website_manifests_but_not_page_chunks(monkeypatch):
    """RAG/chunk searches must not retrieve metadata-only website records."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("baseball")

    filters = os_client.bodies[-1]["query"]["hybrid"].get("filter", [])
    assert {"terms": {"record_kind": ["web_page_manifest", "web_source"]}} in [
        clause["bool"]["must_not"][0]
        for clause in filters
        if clause.get("bool", {}).get("must_not")
    ]


@pytest.mark.asyncio
async def test_dls_hybrid_conflict_retries_as_bool_should(monkeypatch):
    """DLS wraps hybrid in function_score; service must retry as bool/should without pipeline."""

    class _DLSOpenSearch:
        def __init__(self):
            self.bodies: list[dict] = []
            self.params_list: list[dict] = []

        async def search(self, *, index, body, params):
            if body.get("size") == 0:
                return {"aggregations": {"embedding_spaces": {"buckets": []}, "legacy_embedding_models": {"buckets": []}}}
            self.bodies.append(body)
            self.params_list.append(params)
            if len(self.bodies) == 1:
                raise RequestError(
                    400,
                    "search_phase_execution_exception",
                    {"error": {"root_cause": [{"reason": "hybrid query must be a top level query and cannot be wrapped into other queries"}]}},
                )
            return {"hits": {"hits": []}, "aggregations": {}}

    os_client = _DLSOpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    first, retry = os_client.bodies
    # First attempt was hybrid
    assert "hybrid" in first["query"]
    assert os_client.params_list[0].get("search_pipeline") is not None
    # Retry is bool/should with no pipeline
    assert "bool" in retry["query"]
    assert "hybrid" not in retry["query"]
    assert "search_pipeline" not in os_client.params_list[1]
    # Retry preserves the same sub-queries from the hybrid clause
    should_clauses = retry["query"]["bool"]["should"]
    assert len(should_clauses) >= 2  # semantic dis_max + at least one keyword clause
    # num_candidates must be absent from all kNN params in the DLS fallback
    knn_params = [
        params
        for clause in should_clauses
        for knn_clause in clause.get("dis_max", {}).get("queries", [])
        for params in knn_clause.get("knn", {}).values()
    ]
    assert all("num_candidates" not in p for p in knn_params)


@pytest.mark.asyncio
async def test_dls_fallback_preserves_filters(monkeypatch):
    """DLS bool/should retry must carry the original filters into the bool clause."""

    class _DLSOpenSearch:
        def __init__(self):
            self.bodies: list[dict] = []

        async def search(self, *, index, body, params):
            if body.get("size") == 0:
                return {"aggregations": {"embedding_spaces": {"buckets": []}, "legacy_embedding_models": {"buckets": []}}}
            self.bodies.append(body)
            if len(self.bodies) == 1:
                raise RequestError(
                    400,
                    "search_phase_execution_exception",
                    {"error": {"root_cause": [{"reason": "hybrid query must be a top level query"}]}},
                )
            return {"hits": {"hits": []}, "aggregations": {}}

    os_client = _DLSOpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_result_mode("chunks")

    await service.search_tool("baseball")

    retry_body = os_client.bodies[-1]
    assert "bool" in retry_body["query"]
    # record_kind filter must still be present in the fallback
    filters = retry_body["query"]["bool"].get("filter", [])
    record_kind_filter_present = any(
        clause.get("bool", {}).get("must_not", [{}])[0].get("terms", {}).get("record_kind")
        for clause in filters
        if clause.get("bool", {}).get("must_not")
    )
    assert record_kind_filter_present, "record_kind filter missing from DLS fallback"


@pytest.mark.asyncio
async def test_score_threshold_post_filters_chunks_when_pipeline_ran(monkeypatch):
    """Python post-filter removes chunks below the threshold when the pipeline ran."""
    monkeypatch.setattr("config.search_constants.DEFAULT_SEARCH_SCORE_THRESHOLD", 0.1)

    class _ScoredOpenSearch:
        def __init__(self):
            self.bodies: list[dict] = []

        async def search(self, *, index, body, params):
            if body.get("size") == 0:
                return {"aggregations": {"embedding_spaces": {"buckets": []}, "legacy_embedding_models": {"buckets": []}}}
            self.bodies.append(body)
            # Return two hits: one above threshold, one below
            return {
                "hits": {
                    "hits": [
                        {"_score": 0.8, "_source": {"filename": "good.pdf", "text": "relevant content"}},
                        {"_score": 0.05, "_source": {"filename": "bad.pdf", "text": "irrelevant content"}},
                    ]
                },
                "aggregations": {},
            }

    os_client = _ScoredOpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)  # request threshold=0 → falls back to DEFAULT (0.1)

    response = await service.search_tool("MCP")

    filenames = [c["filename"] for c in response["results"]]
    assert "good.pdf" in filenames
    assert "bad.pdf" not in filenames  # 0.05 < 0.1 threshold


@pytest.mark.asyncio
async def test_dls_fallback_skips_score_threshold_post_filter(monkeypatch):
    """When DLS forces bool/should fallback, scores are raw so threshold must not apply."""
    monkeypatch.setattr("config.search_constants.DEFAULT_SEARCH_SCORE_THRESHOLD", 0.1)

    class _DLSScoredOpenSearch:
        def __init__(self):
            self.call_count = 0

        async def search(self, *, index, body, params):
            if body.get("size") == 0:
                return {"aggregations": {"embedding_spaces": {"buckets": []}, "legacy_embedding_models": {"buckets": []}}}
            self.call_count += 1
            if self.call_count == 1:
                raise RequestError(
                    400,
                    "search_phase_execution_exception",
                    {"error": {"root_cause": [{"reason": "hybrid query must be a top level query"}]}},
                )
            # DLS fallback: raw unnormalized scores (e.g. 0.03 is a real result)
            return {
                "hits": {
                    "hits": [
                        {"_score": 0.03, "_source": {"filename": "dls_result.pdf", "text": "some content"}},
                    ]
                },
                "aggregations": {},
            }

    os_client = _DLSScoredOpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    response = await service.search_tool("MCP")

    # 0.03 < 0.1 threshold, but threshold must NOT be applied to raw DLS fallback scores
    filenames = [c["filename"] for c in response["results"]]
    assert "dls_result.pdf" in filenames


@pytest.mark.asyncio
async def test_dls_fallback_is_single_step(monkeypatch):
    """Without num_candidates the DLS error fires on the first attempt — one retry, not two."""

    class _DLSOnFirstAttempt:
        def __init__(self):
            self.bodies: list[dict] = []
            self.params_list: list[dict] = []

        async def search(self, *, index, body, params):
            if body.get("size") == 0:
                return {"aggregations": {"embedding_spaces": {"buckets": []}, "legacy_embedding_models": {"buckets": []}}}
            self.bodies.append(body)
            self.params_list.append(params)
            if len(self.bodies) == 1:
                raise RequestError(
                    400,
                    "search_phase_execution_exception",
                    {"error": {"root_cause": [{"reason": "hybrid query must be a top level query and cannot be wrapped into other queries"}]}},
                )
            return {"hits": {"hits": [{"_score": 0.9, "_source": {"filename": "result.pdf", "text": "some content"}}]}, "aggregations": {}}

    os_client = _DLSOnFirstAttempt()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    response = await service.search_tool("MCP")

    # Exactly two attempts: hybrid → bool/should
    assert len(os_client.bodies) == 2
    assert "hybrid" in os_client.bodies[0]["query"]
    assert os_client.params_list[0].get("search_pipeline") is not None
    assert "bool" in os_client.bodies[1]["query"]
    assert "search_pipeline" not in os_client.params_list[1]
    assert response["results"][0]["filename"] == "result.pdf"


_DATE = {"created_after": "2024-01-01T00:00:00Z"}
_DATE_CLAUSE = build_date_range_query("indexed_time", gte="2024-01-01T00:00:00Z")


@pytest.mark.asyncio
async def test_filters_are_pushed_into_each_knn_clause(monkeypatch):
    """Filters must constrain kNN neighbor selection, not only post-filter the top-k."""
    os_client = _OpenSearch()
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_filters(_DATE)

    await service.search_tool("MCP")

    params = _knn_params(os_client.bodies[-1]["query"])
    assert params
    for knn in params:
        # The date range sits beside the chunk-mode exclusion of website manifests.
        assert _DATE_CLAUSE in knn["filter"]["bool"]["filter"]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["jvector", "lucene", "faiss"])
async def test_engines_with_native_filtering_get_the_inner_knn_filter(monkeypatch, engine):
    os_client = _OpenSearch(
        vector_field={"type": "knn_vector", "method": {"engine": engine, "space_type": "l2"}}
    )
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_filters(_DATE)

    await service.search_tool("MCP")

    params = _knn_params(os_client.bodies[-1]["query"])
    assert params and all("filter" in knn for knn in params)


@pytest.mark.asyncio
async def test_nmslib_scores_the_filtered_documents_exactly(monkeypatch):
    os_client = _OpenSearch(
        vector_field={
            "type": "knn_vector",
            "method": {"engine": "nmslib", "space_type": "cosinesimil"},
        }
    )
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_filters(_DATE)

    await service.search_tool("MCP")

    hybrid = os_client.bodies[-1]["query"]["hybrid"]
    assert _knn_params(os_client.bodies[-1]["query"]) == []  # no native kNN clause for nmslib
    (clause,) = hybrid["queries"][0]["dis_max"]["queries"]
    script = clause["script_score"]["script"]
    assert script["lang"] == "knn"
    assert script["params"]["space_type"] == "cosinesimil"
    assert _DATE_CLAUSE in clause["script_score"]["query"]["bool"]["filter"]
    assert _DATE_CLAUSE in hybrid["filter"]  # the outer filter is kept


@pytest.mark.asyncio
async def test_nmslib_chunk_search_without_dates_still_avoids_the_inner_filter(monkeypatch):
    """The chunk-mode record-kind exclusion alone is a filter, so nmslib must not get it inline."""
    os_client = _OpenSearch(vector_field={"type": "knn_vector", "method": {"engine": "nmslib"}})
    service = _make_service(os_client, monkeypatch)
    _set_context(0)

    await service.search_tool("MCP")

    assert _knn_params(os_client.bodies[-1]["query"]) == []


@pytest.mark.asyncio
async def test_unreadable_mapping_keeps_the_native_knn_filter(monkeypatch):
    os_client = _OpenSearch()  # no `indices`: the mapping cannot be read
    service = _make_service(os_client, monkeypatch)
    _set_context(0)
    set_search_filters(_DATE)

    await service.search_tool("MCP")

    params = _knn_params(os_client.bodies[-1]["query"])
    assert params and all("filter" in knn for knn in params)
