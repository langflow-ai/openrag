from types import SimpleNamespace

import pytest

from auth_context import set_auth_context, set_score_threshold, set_search_filters, set_search_limit
from services.search_service import SearchService


class _OpenSearch:
    def __init__(self):
        self.final_body = None

    async def search(self, *, index, body, params):
        if body.get("size") == 0 and "embedding_spaces" in body.get("aggs", {}):
            composite = body["aggs"]["embedding_spaces"]["composite"]
            if composite.get("after"):
                return {
                    "aggregations": {
                        "embedding_spaces": {
                            "buckets": [{"key": {"space_id": "azure_ai:embed-v2"}, "doc_count": 1}]
                        }
                    }
                }
            return {
                "aggregations": {
                    "embedding_spaces": {
                        "buckets": [
                            {
                                "key": {"space_id": "azure:text-embedding-3-small"},
                                "doc_count": 2,
                            }
                        ],
                        "after_key": {"space_id": "azure:text-embedding-3-small"},
                    },
                }
            }
        if body.get("size") == 0 and "legacy_embedding_models" in body.get("aggs", {}):
            assert body["query"]["bool"]["must_not"] == [
                {"exists": {"field": "embedding_space_id"}}
            ]
            return {
                "aggregations": {
                    "legacy_embedding_models": {
                        "buckets": [
                            {
                                "key": {"model": "text-embedding-3-small"},
                                "doc_count": 3,
                            }
                        ]
                    }
                }
            }
        self.final_body = body
        return {"hits": {"hits": []}, "aggregations": {}}


@pytest.mark.asyncio
async def test_backend_search_queries_exact_and_legacy_embedding_providers(monkeypatch):
    opensearch = _OpenSearch()
    service = object.__new__(SearchService)
    service.session_manager = SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt_token: opensearch
    )
    service.models_service = None
    routes = []

    async def create_embedding(body):
        routes.append(body["model"])
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(
        "services.search_service.gateway_embeddings",
        create_embedding,
    )
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

    await service.search_tool("needle", embedding_model="text-embedding-3-small")

    assert routes == [
        "space:azure:text-embedding-3-small",
        "space:azure_ai:embed-v2",
        "legacy:text-embedding-3-small",
    ]
    knn_queries = opensearch.final_body["query"]["bool"]["should"][0]["dis_max"]["queries"]
    assert [next(iter(query["knn"])) for query in knn_queries] == [
        "chunk_embedding_azure_text_embedding_3_small",
        "chunk_embedding_azure_ai_embed_v2",
        "chunk_embedding_text_embedding_3_small",
    ]
