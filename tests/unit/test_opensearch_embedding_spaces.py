import importlib
import sys
from types import ModuleType, SimpleNamespace

from custom_components.openrag.embedding_spaces import (
    INDEXED_ROUTE_PREFIX,
    LEGACY_ROUTE_PREFIX,
    build_embedding_space_aggregation,
    embedding_spaces_from_aggregation,
)


def _load_opensearch_module(monkeypatch):
    class Input:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name", "")

    class VectorStore:
        inputs = []

    class Data(dict):
        def __init__(self, text=None, **kwargs):
            super().__init__(text=text, **kwargs)

    class Table(list):
        pass

    logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )

    modules = {
        "lfx": ModuleType("lfx"),
        "lfx.base": ModuleType("lfx.base"),
        "lfx.base.vectorstores": ModuleType("lfx.base.vectorstores"),
        "lfx.base.vectorstores.model": ModuleType("lfx.base.vectorstores.model"),
        "lfx.base.vectorstores.vector_store_connection_decorator": ModuleType(
            "lfx.base.vectorstores.vector_store_connection_decorator"
        ),
        "lfx.io": ModuleType("lfx.io"),
        "lfx.log": ModuleType("lfx.log"),
        "lfx.schema": ModuleType("lfx.schema"),
        "lfx.schema.data": ModuleType("lfx.schema.data"),
        "lfx.schema.dataframe": ModuleType("lfx.schema.dataframe"),
    }
    modules["lfx.base.vectorstores.model"].LCVectorStoreComponent = VectorStore
    modules["lfx.base.vectorstores.model"].check_cached_vector_store = lambda func: func
    modules["lfx.base.vectorstores.vector_store_connection_decorator"].vector_store_connection = (
        lambda cls: cls
    )
    for name in (
        "BoolInput",
        "DropdownInput",
        "HandleInput",
        "IntInput",
        "MultilineInput",
        "Output",
        "SecretStrInput",
        "StrInput",
        "TableInput",
    ):
        setattr(modules["lfx.io"], name, Input)
    modules["lfx.log"].logger = logger
    modules["lfx.schema.data"].Data = Data
    modules["lfx.schema.dataframe"].Table = Table
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    sys.modules.pop("custom_components.openrag.opensearch_multimodal", None)
    return importlib.import_module("custom_components.openrag.opensearch_multimodal")


class _Indices:
    def __init__(self, fields):
        self.fields = fields

    def get_mapping(self, *, index):
        return {index: {"mappings": {"properties": self.fields}}}


class _SearchClient:
    def __init__(self, aggregation, fields):
        self.aggregation = aggregation
        self.indices = _Indices(fields)
        self.query = None

    def search(self, *, index, body, params):
        if body.get("size") == 0:
            aggregation_name = next(iter(body["aggs"]))
            return {
                "aggregations": {
                    aggregation_name: self.aggregation["aggregations"].get(
                        aggregation_name, {"buckets": []}
                    )
                }
            }
        self.query = body
        return {"hits": {"hits": []}}


def _component(module, client, embedding):
    component = module.OpenSearchVectorStoreComponentMultimodalMultiEmbedding()
    component.embedding = embedding
    component.index_name = "documents"
    component.ingest_data = None
    component.filter_expression = ""
    component.number_of_results = 10
    component.num_candidates = 0
    component.vector_field = "chunk_embedding"
    component.build_client = lambda: client
    component.log = lambda message: None
    return component


def test_detection_separates_provider_qualified_and_legacy_spaces() -> None:
    result = {
        "aggregations": {
            "embedding_spaces": {
                "buckets": [{"key": {"space_id": "azure:text-embedding-3-small"}, "doc_count": 4}]
            },
            "legacy_embedding_models": {
                "buckets": [{"key": {"model": "text-embedding-3-small"}, "doc_count": 3}],
            },
        }
    }

    spaces = embedding_spaces_from_aggregation(result)

    assert [(space.space_id, space.route_model, space.field_identity) for space in spaces] == [
        (
            "azure:text-embedding-3-small",
            f"{INDEXED_ROUTE_PREFIX}azure:text-embedding-3-small",
            "azure:text-embedding-3-small",
        ),
        (
            "legacy:text-embedding-3-small",
            f"{LEGACY_ROUTE_PREFIX}text-embedding-3-small",
            "text-embedding-3-small",
        ),
    ]


def test_detection_aggregation_only_treats_documents_without_space_id_as_legacy() -> None:
    aggregation = build_embedding_space_aggregation(size=25)

    assert aggregation["embedding_spaces"]["composite"] == {
        "size": 25,
        "sources": [{"space_id": {"terms": {"field": "embedding_space_id"}}}],
    }
    assert aggregation["legacy_embedding_models"]["composite"] == {
        "size": 25,
        "sources": [{"model": {"terms": {"field": "embedding_model"}}}],
    }


def test_search_queries_every_resolvable_provider_space(monkeypatch) -> None:
    module = _load_opensearch_module(monkeypatch)
    aggregation = {
        "aggregations": {
            "embedding_spaces": {
                "buckets": [{"key": {"space_id": "azure:text-embedding-3-small"}, "doc_count": 2}]
            },
            "legacy_embedding_models": {
                "buckets": [{"key": {"model": "text-embedding-3-small"}, "doc_count": 2}]
            },
        }
    }
    fields = {
        "chunk_embedding_azure_text_embedding_3_small": {
            "type": "knn_vector",
            "dimension": 2,
        },
        "chunk_embedding_text_embedding_3_small": {
            "type": "knn_vector",
            "dimension": 2,
        },
        "filename": {"type": "keyword"},
    }
    client = _SearchClient(aggregation, fields)
    routes = []

    class Child:
        def __init__(self, route):
            self.model = route

        def embed_query(self, query):
            return [0.1, 0.2]

    class Root(Child):
        deployment = "selected-model"

        def for_model(self, route):
            routes.append(route)
            return Child(route)

    _component(module, client, Root("selected-model")).search("needle")

    assert routes == [
        "space:azure:text-embedding-3-small",
        "legacy:text-embedding-3-small",
    ]
    knn_queries = client.query["query"]["bool"]["should"][0]["dis_max"]["queries"]
    assert {next(iter(query["knn"])) for query in knn_queries} == {
        "chunk_embedding_azure_text_embedding_3_small",
        "chunk_embedding_text_embedding_3_small",
    }


def test_detection_paginates_all_embedding_spaces(monkeypatch) -> None:
    module = _load_opensearch_module(monkeypatch)

    class PagingClient:
        def __init__(self):
            self.calls = []

        def search(self, *, index, body, params):
            self.calls.append(body)
            exact = body["aggs"].get("embedding_spaces")
            if exact and exact["composite"].get("after"):
                return {
                    "aggregations": {
                        "embedding_spaces": {"buckets": [{"key": {"space_id": "watsonx:slate"}}]}
                    }
                }
            if exact:
                return {
                    "aggregations": {
                        "embedding_spaces": {
                            "buckets": [{"key": {"space_id": "azure:embed-v1"}}],
                            "after_key": {"space_id": "azure:embed-v1"},
                        }
                    }
                }
            return {
                "aggregations": {
                    "legacy_embedding_models": {"buckets": []},
                }
            }

    client = PagingClient()
    component = _component(module, client, None)

    spaces = component._detect_available_models(client)

    assert [space.space_id for space in spaces] == ["azure:embed-v1", "watsonx:slate"]
    assert len(client.calls) == 3
    assert "legacy_embedding_models" not in client.calls[1]["aggs"]
    assert client.calls[2]["query"]["bool"]["must_not"] == [
        {"exists": {"field": "embedding_space_id"}}
    ]


def test_search_falls_back_to_keywords_when_no_space_resolves(monkeypatch) -> None:
    module = _load_opensearch_module(monkeypatch)
    aggregation = {
        "aggregations": {
            "embedding_spaces": {"buckets": []},
            "legacy_embedding_models": {
                "buckets": [{"key": {"model": "unknown-model"}, "doc_count": 1}]
            },
        }
    }
    client = _SearchClient(aggregation, {"filename": {"type": "keyword"}})

    class Root:
        model = "selected-model"
        deployment = "selected-model"

        def for_model(self, route):
            raise RuntimeError("unmapped legacy model")

    _component(module, client, Root()).search("needle")

    should = client.query["query"]["bool"]["should"]
    assert len(should) == 1
    assert "multi_match" in should[0]
    assert client.query["query"]["bool"]["filter"] == []


def test_search_remains_keyword_capable_without_embedding_adapter(monkeypatch) -> None:
    module = _load_opensearch_module(monkeypatch)
    aggregation = {
        "aggregations": {
            "embedding_spaces": {
                "buckets": [{"key": {"space_id": "azure:text-embedding-3-small"}, "doc_count": 1}]
            },
            "legacy_embedding_models": {"buckets": []},
        }
    }
    client = _SearchClient(aggregation, {"filename": {"type": "keyword"}})

    _component(module, client, None).search("needle")

    assert client.query["query"]["bool"]["should"] == [
        {
            "multi_match": {
                "query": "needle",
                "fields": ["text^2", "filename^1.5"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "boost": 1.0,
            }
        }
    ]


def test_direct_ingest_persists_provider_qualified_space(monkeypatch) -> None:
    module = _load_opensearch_module(monkeypatch)
    component = module.OpenSearchVectorStoreComponentMultimodalMultiEmbedding()
    component._openrag_ingest_callback_config = lambda: None
    component.log = lambda message: None
    captured = []
    monkeypatch.setattr(
        module.helpers, "bulk", lambda client, requests, **kwargs: captured.extend(requests)
    )

    component._bulk_ingest_embeddings(
        client=object(),
        index_name="documents",
        embeddings=[[0.1, 0.2]],
        texts=["hello"],
        vector_field="chunk_embedding_azure_text_embedding_3_small",
        embedding_model="text-embedding-3-small",
        embedding_provider="azure",
        embedding_space_id="azure:text-embedding-3-small",
    )

    assert captured[0]["embedding_model"] == "text-embedding-3-small"
    assert captured[0]["embedding_provider"] == "azure"
    assert captured[0]["embedding_space_id"] == "azure:text-embedding-3-small"
