"""Unit tests for the hybrid search query builder and scoring pipeline.

Covers:
- Query body structure (hybrid vs keyword-only fallback)
- search_pipeline param attachment
- Noise / stopword / exact-token detection
- Keyword stripping (_keyword_query)
- Pipeline body construction (ensure_hybrid_search_pipeline)
- Score threshold migration (score in [0,1] after processor)
- Edge cases: empty query, wildcard, single-word, multi-model, filter interaction
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.search_constants import (  # noqa: E402
    DEFAULT_SEARCH_SCORE_THRESHOLD,
    HYBRID_PIPELINE_NAME,
    KEYWORD_WEIGHT,
    SEMANTIC_WEIGHT,
)
from services.search_service import (  # noqa: E402
    _is_noise_query,
    _is_exact_token_query,
    _keyword_query,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(captured_bodies: list, captured_params: list, *, hit_score: float = 0.85):
    """Return a SearchService whose OpenSearch client records every search call."""
    from services.search_service import SearchService

    fake_hit = {
        "_score": hit_score,
        "_id": "chunk-1",
        "_source": {
            "filename": "doc.pdf",
            "mimetype": "application/pdf",
            "page": 1,
            "text": "relevant content about machine learning",
            "source_url": "",
            "owner": "user@example.com",
            "owner_name": "User",
            "owner_email": "user@example.com",
            "file_size": 1024,
            "connector_type": "local",
            "embedding_model": "text-embedding-3-small",
            "embedding_provider": "openai",
            "embedding_space_id": "openai__text-embedding-3-small",
            "embedding_dimensions": 1536,
            "parser": "docling",
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "allowed_users": [],
            "allowed_groups": [],
            "allowed_principal_labels": [],
        },
    }

    async def fake_search(index, body, params=None):
        captured_bodies.append(body)
        captured_params.append(params or {})
        return {
            "hits": {"hits": [fake_hit], "total": {"value": 1}},
            "aggregations": {},
            "took": 5,
        }

    fake_os_client = MagicMock()
    fake_os_client.search = fake_search

    fake_session_manager = MagicMock()
    fake_session_manager.get_user_opensearch_client.return_value = fake_os_client

    svc = SearchService(session_manager=fake_session_manager)
    return svc


def _patch_auth(monkeypatch, *, user_id="user-1", jwt_token="tok"):
    monkeypatch.setattr("services.search_service.get_auth_context", lambda: (user_id, jwt_token))


def _patch_context(monkeypatch, *, filters=None, limit=10, threshold=0.0):
    import auth_context

    monkeypatch.setattr(auth_context, "get_search_filters", lambda: filters or {})
    monkeypatch.setattr(auth_context, "get_search_limit", lambda: limit)
    monkeypatch.setattr(auth_context, "get_score_threshold", lambda: threshold)


def _patch_embedding(monkeypatch, *, vector=None, field_identity="openai__text-embedding-3-small"):
    """Stub the embedding gateway and corpus space detection to return one space."""
    from utils.embedding_fields import EmbeddingSpace, INDEXED_EMBEDDING_ROUTE_PREFIX

    vec = vector or [0.1] * 8

    space = EmbeddingSpace(
        space_id=field_identity,
        route_model=f"{INDEXED_EMBEDDING_ROUTE_PREFIX}{field_identity}",
        field_identity=field_identity,
    )

    async def fake_gateway(body, **_):
        return {"data": [{"embedding": vec}]}

    async def fake_agg_search(index, body, params=None):
        # Returns a minimal aggregation result so space detection resolves one space
        return {
            "hits": {"hits": [], "total": {"value": 0}},
            "aggregations": {
                "embedding_spaces": {
                    "buckets": [
                        {
                            "key": field_identity,
                            "top_hits": {
                                "hits": {
                                    "hits": [
                                        {
                                            "_source": {
                                                "embedding_space_id": field_identity,
                                                "embedding_model": "text-embedding-3-small",
                                                "embedding_provider": "openai",
                                            }
                                        }
                                    ]
                                }
                            },
                        }
                    ],
                    "after_key": None,
                }
            },
        }

    monkeypatch.setattr("services.search_service.gateway_embeddings", fake_gateway)
    monkeypatch.setattr(
        "services.search_service.embedding_spaces_from_aggregation",
        lambda _: [space],
    )
    monkeypatch.setattr(
        "services.search_service.embedding_space_after_keys",
        lambda _: (None, None),
    )


# ---------------------------------------------------------------------------
# 1. Query body structure
# ---------------------------------------------------------------------------


class TestQueryBodyStructure:
    @pytest.mark.asyncio
    async def test_hybrid_query_used_when_embeddings_available(self, monkeypatch):
        """When an embedding succeeds the query top-level key is 'hybrid'."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("machine learning", "text-embedding-3-small")

        assert bodies, "no search call was made"
        query = bodies[-1]["query"]
        assert "hybrid" in query, f"expected hybrid query, got: {list(query.keys())}"

    @pytest.mark.asyncio
    async def test_hybrid_has_semantic_and_keyword_sub_queries(self, monkeypatch):
        """hybrid.queries[0] is the semantic dis_max, remaining are keyword clauses."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("what is retrieval augmented generation", "text-embedding-3-small")

        hybrid = bodies[-1]["query"]["hybrid"]
        queries = hybrid["queries"]
        assert len(queries) >= 2, "expected at least semantic + one keyword clause"
        assert "dis_max" in queries[0], "first sub-query should be the semantic dis_max"
        # Remaining clauses must be keyword types
        keyword_types = {list(q.keys())[0] for q in queries[1:]}
        assert keyword_types <= {"multi_match", "match_phrase_prefix"}

    @pytest.mark.asyncio
    async def test_keyword_only_fallback_when_no_embeddings(self, monkeypatch):
        """When embedding fails the query falls back to bool/should."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)

        # No embedding patched → available_spaces stays empty → no knn_queries
        monkeypatch.setattr(
            "services.search_service.embedding_spaces_from_aggregation", lambda _: []
        )
        monkeypatch.setattr(
            "services.search_service.embedding_space_after_keys", lambda _: (None, None)
        )
        monkeypatch.setattr(
            "services.search_service.get_openrag_config",
            lambda: SimpleNamespace(
                knowledge=SimpleNamespace(
                    embedding_provider="openai",
                    embedding_model="text-embedding-3-small",
                    disable_ingest_with_langflow=False,
                )
            ),
        )

        await svc._search("machine learning", "text-embedding-3-small")

        query = bodies[-1]["query"]
        assert "bool" in query, f"expected bool fallback, got: {list(query.keys())}"
        assert "hybrid" not in query

    @pytest.mark.asyncio
    async def test_wildcard_uses_match_all(self, monkeypatch):
        """A '*' query never hits the hybrid path."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)

        await svc._search("*", "text-embedding-3-small")

        query = bodies[-1]["query"]
        assert "hybrid" not in query
        assert "function_score" not in query
        assert "match_all" in query or "bool" in query

    @pytest.mark.asyncio
    async def test_no_function_score_wrapper(self, monkeypatch):
        """function_score must not appear anywhere in the query (it broke hybrid)."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("vector search", "text-embedding-3-small")

        import json
        body_str = json.dumps(bodies[-1])
        assert "function_score" not in body_str

    @pytest.mark.asyncio
    async def test_filters_embedded_in_hybrid_clause(self, monkeypatch):
        """Filters must appear inside the hybrid clause, not as a top-level wrapper."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch, filters={"data_sources": ["doc.pdf"]})
        _patch_embedding(monkeypatch)

        await svc._search("machine learning", "text-embedding-3-small")

        query = bodies[-1]["query"]
        assert "hybrid" in query
        assert "filter" in query["hybrid"]


# ---------------------------------------------------------------------------
# 2. Pipeline parameter
# ---------------------------------------------------------------------------


class TestPipelineParam:
    @pytest.mark.asyncio
    async def test_pipeline_param_attached_for_hybrid(self, monkeypatch):
        """search_pipeline must be in params when a hybrid query is issued."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("semantic search", "text-embedding-3-small")

        assert params, "no search call recorded"
        assert params[-1].get("search_pipeline") == HYBRID_PIPELINE_NAME

    @pytest.mark.asyncio
    async def test_no_pipeline_param_for_keyword_only(self, monkeypatch):
        """Keyword-only fallback must NOT send the pipeline param."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        monkeypatch.setattr(
            "services.search_service.embedding_spaces_from_aggregation", lambda _: []
        )
        monkeypatch.setattr(
            "services.search_service.embedding_space_after_keys", lambda _: (None, None)
        )
        monkeypatch.setattr(
            "services.search_service.get_openrag_config",
            lambda: SimpleNamespace(
                knowledge=SimpleNamespace(
                    embedding_provider="openai",
                    embedding_model="text-embedding-3-small",
                    disable_ingest_with_langflow=False,
                )
            ),
        )

        await svc._search("keyword only query", "text-embedding-3-small")

        assert "search_pipeline" not in params[-1]

    @pytest.mark.asyncio
    async def test_no_pipeline_param_for_wildcard(self, monkeypatch):
        """Wildcard queries must NOT send the pipeline param."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)

        await svc._search("*", "text-embedding-3-small")

        assert "search_pipeline" not in params[-1]


# ---------------------------------------------------------------------------
# 3. Noise / stopword / exact-token detection (pure functions)
# ---------------------------------------------------------------------------


class TestNoiseQuery:
    @pytest.mark.parametrize("query", [
        "asdfgh",
        "qwerty",
        "zzzzzz",
        "jjjjjj",
        "qwertyu",
        "asdfghjkl",
    ])
    def test_keyboard_mash_is_noise(self, query):
        assert _is_noise_query(query), f"'{query}' should be noise"

    @pytest.mark.parametrize("query", [
        "machine learning",
        "what is RAG",
        "the",            # stopword but real word — not noise
        "https",          # vowel-poor but not mash
        "pgsql",          # abbreviation
        "strengths",      # consonant-heavy English word
        "vitamin",        # real word, prefix of vitaminC
        "a",              # single letter
    ])
    def test_real_words_are_not_noise(self, query):
        assert not _is_noise_query(query), f"'{query}' should NOT be noise"

    def test_mixed_mash_and_real_skips_semantic(self):
        # "asdfgh machine" — not ALL tokens are noise, so not a noise query
        assert not _is_noise_query("asdfgh machine")

    def test_empty_string_is_not_noise(self):
        assert not _is_noise_query("")

    def test_numbers_are_not_noise(self):
        # digits are filtered by isalpha()
        assert not _is_noise_query("12345")


class TestExactTokenQuery:
    @pytest.mark.parametrize("query", [
        "v1.2.3",
        "SKU-98765",
        "error_code_404",
        "abc123",
        "GPT-4o",
        "C++",
    ])
    def test_code_like_queries_are_exact(self, query):
        assert _is_exact_token_query(query), f"'{query}' should be exact-token"

    @pytest.mark.parametrize("query", [
        "machine learning",
        "what is retrieval",
        "the quick brown fox",
        "a",
        "",
        "ab",
    ])
    def test_prose_queries_are_not_exact(self, query):
        assert not _is_exact_token_query(query), f"'{query}' should NOT be exact-token"


# ---------------------------------------------------------------------------
# 4. Keyword query stopword stripping
# ---------------------------------------------------------------------------


class TestKeywordQuery:
    def test_stopwords_stripped_from_multi_word(self):
        result = _keyword_query("what is machine learning")
        assert "machine" in result
        assert "learning" in result
        assert "what" not in result
        assert "is" not in result

    def test_single_word_returned_unchanged(self):
        assert _keyword_query("the") == "the"
        assert _keyword_query("machine") == "machine"

    def test_all_stopwords_returns_original(self):
        # Every token is a stopword — fall back to original query
        result = _keyword_query("the a is")
        assert result == "the a is"

    def test_punctuation_stripped_before_stopword_check(self):
        result = _keyword_query("what, is machine learning?")
        assert "machine" in result
        assert "learning" in result

    def test_empty_string(self):
        assert _keyword_query("") == ""

    def test_non_stopwords_preserved(self):
        result = _keyword_query("retrieval augmented generation")
        assert result == "retrieval augmented generation"


# ---------------------------------------------------------------------------
# 5. Pipeline body construction
# ---------------------------------------------------------------------------


class TestEnsureHybridSearchPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_body_sent_to_correct_endpoint(self):
        """ensure_hybrid_search_pipeline PUTs the normalization processor body."""
        from utils.opensearch_init import ensure_hybrid_search_pipeline

        put_calls = []

        class FakeHttp:
            async def put(self, path, body=None):
                put_calls.append({"path": path, "body": body})

        fake_client = SimpleNamespace(http=FakeHttp())

        await ensure_hybrid_search_pipeline(fake_client)

        assert len(put_calls) == 1
        call = put_calls[0]
        assert call["path"] == f"/_search/pipeline/{HYBRID_PIPELINE_NAME}"

        processor = call["body"]["phase_results_processors"][0]["normalization-processor"]
        assert processor["normalization"]["technique"] == "min_max"
        assert processor["combination"]["technique"] == "arithmetic_mean"
        weights = processor["combination"]["parameters"]["weights"]
        assert weights == [SEMANTIC_WEIGHT, KEYWORD_WEIGHT]
        assert abs(sum(weights) - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_pipeline_creation_failure_is_non_fatal(self):
        """A failed pipeline PUT must not raise — hybrid falls back gracefully."""
        from utils.opensearch_init import ensure_hybrid_search_pipeline

        class BrokenHttp:
            async def put(self, path, body=None):
                raise ConnectionError("OpenSearch unreachable")

        fake_client = SimpleNamespace(http=BrokenHttp())

        # Must not raise
        await ensure_hybrid_search_pipeline(fake_client)


# ---------------------------------------------------------------------------
# 6. Score constants from shared JSON
# ---------------------------------------------------------------------------


class TestScoringConstants:
    def test_threshold_in_normalised_range(self):
        """After migrating to the processor, threshold must be in [0, 1]."""
        assert 0.0 <= DEFAULT_SEARCH_SCORE_THRESHOLD <= 1.0

    def test_weights_sum_to_one(self):
        assert abs(SEMANTIC_WEIGHT + KEYWORD_WEIGHT - 1.0) < 1e-9

    def test_semantic_weight_dominates(self):
        """Default config favours semantic search over keyword."""
        assert SEMANTIC_WEIGHT > KEYWORD_WEIGHT

    def test_pipeline_name_is_non_empty_string(self):
        assert isinstance(HYBRID_PIPELINE_NAME, str)
        assert len(HYBRID_PIPELINE_NAME) > 0


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_noise_query_skips_semantic_uses_keyword_only(self, monkeypatch):
        """A noise query must fall back to keyword-only (no hybrid, no pipeline)."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("asdfghjkl", "text-embedding-3-small")

        query = bodies[-1]["query"]
        assert "hybrid" not in query, "noise query must not use hybrid path"
        assert "search_pipeline" not in params[-1]

    @pytest.mark.asyncio
    async def test_single_word_query_builds_valid_body(self, monkeypatch):
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("OpenSearch", "text-embedding-3-small")

        assert bodies, "no query body captured"
        assert "query" in bodies[-1]

    @pytest.mark.asyncio
    async def test_filter_with_empty_values_produces_impossible_clause(self, monkeypatch):
        """An empty filter array must inject an impossible term, not omit the filter."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch, filters={"data_sources": []})
        _patch_embedding(monkeypatch)

        await svc._search("machine learning", "text-embedding-3-small")

        import json
        body_str = json.dumps(bodies[-1])
        assert "__IMPOSSIBLE_VALUE__" in body_str

    @pytest.mark.asyncio
    async def test_multi_model_corpus_knn_clauses_per_model(self, monkeypatch):
        """Each embedding space gets its own knn clause inside dis_max."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)

        from utils.embedding_fields import EmbeddingSpace, INDEXED_EMBEDDING_ROUTE_PREFIX

        spaces = [
            EmbeddingSpace(
                space_id=f"openai__model-{i}",
                route_model=f"{INDEXED_EMBEDDING_ROUTE_PREFIX}openai__model-{i}",
                field_identity=f"openai__model-{i}",
            )
            for i in range(2)
        ]

        async def fake_gateway(body, **_):
            return {"data": [{"embedding": [0.1] * 8}]}

        monkeypatch.setattr("services.search_service.gateway_embeddings", fake_gateway)
        monkeypatch.setattr(
            "services.search_service.embedding_spaces_from_aggregation", lambda _: spaces
        )
        monkeypatch.setattr(
            "services.search_service.embedding_space_after_keys", lambda _: (None, None)
        )

        await svc._search("multi model query", "model-0")

        hybrid = bodies[-1]["query"]["hybrid"]
        knn_queries = hybrid["queries"][0]["dis_max"]["queries"]
        assert len(knn_queries) == 2, "one knn clause per embedding space"

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_error(self, monkeypatch):
        """Missing user_id must return an auth error and never issue a document search."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        monkeypatch.setattr("services.search_service.get_auth_context", lambda: (None, None))
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        result = await svc._search("anything", "text-embedding-3-small")

        assert result.get("error") == "Authentication required"
        # The embedding-space aggregation (size=0) fires before the user_id gate.
        # Only assert that the actual document search (size > 0) never executed.
        search_bodies = [b for b in bodies if b.get("size", 0) > 0]
        assert search_bodies == [], "document search must not execute without user_id"

    @pytest.mark.asyncio
    async def test_highlight_not_requested_for_wildcard(self, monkeypatch):
        """Wildcard queries must omit the highlight block."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)

        await svc._search("*", "text-embedding-3-small")

        assert "highlight" not in bodies[-1]

    @pytest.mark.asyncio
    async def test_highlight_requested_for_real_query(self, monkeypatch):
        """Non-wildcard queries must request keyword highlights."""
        bodies, params = [], []
        svc = _make_service(bodies, params)
        _patch_auth(monkeypatch)
        _patch_context(monkeypatch)
        _patch_embedding(monkeypatch)

        await svc._search("retrieval augmented generation", "text-embedding-3-small")

        assert "highlight" in bodies[-1]
        assert "text" in bodies[-1]["highlight"]["fields"]
