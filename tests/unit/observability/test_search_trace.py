"""One Langfuse trace per search the backend serves (issue 05).

Covers the search API (UI and /v1) and the agent `search_tool`. Retrieval in
Langflow's agent flow runs its own OpenSearch query; the backend only sees its
query embedding, traced by the gateway as `embedding.query`.
"""

from types import SimpleNamespace

import pytest
from langfuse._client.attributes import LangfuseOtelSpanAttributes as LF
from opentelemetry import trace

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from observability import spans
from observability.tracing import trace_context
from services.search_service import SearchService


def _metadata(span, key):
    return span.attributes.get(f"{LF.OBSERVATION_METADATA}.openrag.{key}")


def _trace_metadata(span, key):
    return span.attributes.get(f"{LF.TRACE_METADATA}.openrag.{key}")


HITS = [
    {
        "_id": "doc-a_0",
        "_score": 0.91,
        "_source": {"filename": "a.pdf", "text": "alpha secret text"},
    },
    {"_id": "doc-a_3", "_score": 0.72, "_source": {"filename": "a.pdf", "text": "more alpha"}},
    {"_id": "doc-b_1", "_score": 0.5, "_source": {"filename": "b.pdf", "text": "beta"}},
]


class _OpenSearch:
    def __init__(self, error: Exception | None = None):
        self.error = error

    async def search(self, *, index, body, params):
        if body.get("size") == 0 and "embedding_spaces" in body.get("aggs", {}):
            return {
                "aggregations": {
                    "embedding_spaces": {
                        "buckets": [{"key": {"space_id": "openai:text-embedding-3-small"}}]
                    }
                }
            }
        if body.get("size") == 0:
            return {"aggregations": {}}
        if self.error is not None:
            raise self.error
        return {"took": 7, "hits": {"hits": HITS}, "aggregations": {}}


@pytest.fixture
def service(monkeypatch):
    opensearch = _OpenSearch()
    svc = object.__new__(SearchService)
    svc.session_manager = SimpleNamespace(get_user_opensearch_client=lambda *_: opensearch)
    svc.models_service = None
    svc.opensearch = opensearch
    svc.embed_parents = []
    svc.embed_error = None

    async def create_embedding(body, *, interactive=False):
        svc.embed_parents.append(getattr(trace.get_current_span(), "name", None))
        if svc.embed_error is not None:
            raise svc.embed_error
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("services.search_service.gateway_embeddings", create_embedding)
    monkeypatch.setattr("services.search_service.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.search_service.get_embedding_model", lambda: None)
    monkeypatch.setattr(
        "services.search_service.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_provider="openai", legacy_embedding_provider_map={}
            ),
            providers=SimpleNamespace(ollama=SimpleNamespace(endpoint=None)),
        ),
    )
    set_auth_context("user-1", "jwt")
    set_search_filters({})
    set_search_limit(10)
    set_score_threshold(0)
    return svc


async def _api_search(service, query="gamma", **kwargs):
    return await service.search(
        query,
        user_id="user-1",
        jwt_token="jwt",
        filters=kwargs.pop("filters", {}),
        limit=kwargs.pop("limit", 5),
        score_threshold=kwargs.pop("score_threshold", 0.2),
        embedding_model="text-embedding-3-small",
    )


@pytest.mark.asyncio
async def test_an_api_search_is_one_trace_with_embed_and_query_stages(service, finished):
    response = await _api_search(
        service, filters={"data_sources": ["a.pdf", "b.pdf"], "owners": ["u"]}
    )

    assert response["total"] == 3
    exported = finished()
    root = exported["search"]
    assert root.parent is None
    assert exported["search.embed"].parent.span_id == root.context.span_id
    assert exported["search.query"].parent.span_id == root.context.span_id

    assert root.attributes[LF.TRACE_USER_ID] == "user-1"
    assert "search_source:api" in root.attributes[LF.TRACE_TAGS]
    assert _trace_metadata(root, "search.source") == "api"
    assert _trace_metadata(root, "search.k") == "5"
    assert _trace_metadata(root, "search.score_threshold") == "0.2"
    assert _trace_metadata(root, "search.query_chars") == "5"
    assert _trace_metadata(root, "search.filters") == '{"data_sources": 2, "owners": 1}'
    assert _trace_metadata(root, "embedding_model") == "text-embedding-3-small"

    assert _metadata(root, "search.hit_count") == 3
    assert _metadata(root, "search.top_scores") == "[0.91, 0.72, 0.5]"
    assert _metadata(root, "search.chunk_ids") == '["doc-a_0", "doc-a_3", "doc-b_1"]'


@pytest.mark.asyncio
async def test_stage_spans_record_spaces_and_opensearch_results(service, finished):
    await _api_search(service)

    exported = finished()
    embed = exported["search.embed"]
    assert _metadata(embed, "spaces") == 1
    assert _metadata(embed, "succeeded") == 1
    assert _metadata(embed, "failed") == 0
    assert _metadata(embed, "space_ids") == '["openai:text-embedding-3-small"]'

    query = exported["search.query"]
    assert _metadata(query, "knn_fields") == 1
    assert _metadata(query, "hits") == 3
    assert _metadata(query, "took_ms") == 7


@pytest.mark.asyncio
async def test_query_embeddings_nest_under_the_embed_stage(service, finished):
    await _api_search(service)

    assert service.embed_parents == ["search.embed"]


@pytest.mark.asyncio
async def test_the_agent_tool_is_traced_as_agent_tool(service, finished):
    await service.search_tool("gamma", embedding_model="text-embedding-3-small")

    root = finished()["search"]
    assert _trace_metadata(root, "search.source") == "agent_tool"


@pytest.mark.asyncio
async def test_a_knowledge_filter_from_the_context_is_recorded(service, finished):
    with trace_context(attributes={"openrag.search.filter_id": "filter-1"}):
        await _api_search(service)

    assert _trace_metadata(finished()["search"], "search.filter_id") == "filter-1"


@pytest.mark.asyncio
async def test_query_and_chunk_text_stay_out_unless_capture_is_on(service, finished, monkeypatch):
    await _api_search(service, query="alpha secret")
    for span in finished().values():
        attributes = str(dict(span.attributes))
        assert "alpha secret" not in attributes
        assert "a.pdf" not in attributes

    monkeypatch.setattr(spans, "content_capture_enabled", lambda: True)
    await _api_search(service, query="alpha secret")
    assert _metadata(finished()["search"], "search.query") == "alpha secret"


@pytest.mark.asyncio
async def test_a_failed_query_embedding_degrades_without_failing(service, finished):
    from services.llm_gateway import LlmGatewayError

    service.embed_error = LlmGatewayError("provider removed", 400)

    response = await _api_search(service)

    assert response["warnings"][0]["code"] == "embedding_unavailable"
    exported = finished()
    assert _metadata(exported["search.embed"], "failed") == 1
    root = exported["search"]
    assert _metadata(root, "search.degraded") is True
    assert root.attributes.get(LF.OBSERVATION_LEVEL) != "ERROR"


@pytest.mark.asyncio
async def test_an_opensearch_failure_marks_the_query_stage_and_the_trace(service, finished):
    service.opensearch.error = RuntimeError("cluster unavailable")

    with pytest.raises(RuntimeError):
        await _api_search(service)

    exported = finished()
    assert exported["search.query"].attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    root = exported["search"]
    assert root.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "RuntimeError in search.query"


@pytest.mark.asyncio
async def test_a_wildcard_listing_has_no_embed_stage(service, finished):
    await _api_search(service, query="*")

    exported = finished()
    assert "search.embed" not in exported
    assert _trace_metadata(exported["search"], "search.wildcard") == "True"


@pytest.mark.asyncio
async def test_untraced_search_returns_the_same(service, monkeypatch):
    monkeypatch.setattr(spans, "_client", None)

    response = await _api_search(service)

    assert [chunk["chunk_id"] for chunk in response["results"]] == ["doc-a_0", "doc-a_3", "doc-b_1"]
