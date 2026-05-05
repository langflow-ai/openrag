from __future__ import annotations

import asyncio
import copy
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any, Awaitable, Callable, Dict

from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
from config.settings import (
    clients,
    get_embedding_model,
    get_index_name,
    get_knowledge_backend as get_configured_knowledge_backend,
)
from services.knowledge_access import KnowledgeAccessContext
from utils.file_utils import get_filename_aliases
from utils.logging_config import get_logger

logger = get_logger(__name__)

SearchEmbeddingFn = Callable[[str, str], Awaitable[list[float]]]

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0


class KnowledgeBackend(ABC):
    @abstractmethod
    async def has_indexed_documents(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def index_chunks(
        self,
        chunks: list[dict[str, Any]],
        access_context: KnowledgeAccessContext,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        *,
        query: str,
        embedding_model: str | None,
        filters: Dict[str, Any] | None,
        limit: int,
        score_threshold: float,
        access_context: KnowledgeAccessContext,
        embed_query: SearchEmbeddingFn,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def filename_exists(
        self,
        filename: str,
        access_context: KnowledgeAccessContext,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def document_exists(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_filename(
        self,
        filename: str,
        access_context: KnowledgeAccessContext,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_document_id(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_filter_sets(
        self,
        filter_sets: list[dict[str, Any]],
        *,
        access_context: KnowledgeAccessContext | None = None,
        match_any: bool = True,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    async def list_connector_file_refs(
        self,
        connector_type: str,
        access_context: KnowledgeAccessContext,
    ) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @abstractmethod
    async def refresh(self) -> None:
        raise NotImplementedError


class OpenSearchKnowledgeBackend(KnowledgeBackend):
    def __init__(self, session_manager):
        self.session_manager = session_manager

    async def has_indexed_documents(self) -> bool:
        try:
            result = await clients.opensearch.count(
                index=get_index_name(),
                body={"query": {"match_all": {}}},
            )
        except Exception as exc:
            if "index_not_found_exception" in str(exc):
                return False
            raise
        return (result or {}).get("count", 0) > 0

    def _get_client(self, access_context: KnowledgeAccessContext):
        if self.session_manager is None:
            raise ValueError("Session manager is required for the OpenSearch knowledge backend.")
        return self.session_manager.get_user_opensearch_client(
            access_context.user_id,
            access_context.jwt_token,
        )

    @staticmethod
    def _build_filter_clauses(filters: Dict[str, Any] | None) -> list[dict[str, Any]]:
        if not filters:
            return []

        field_mapping = {
            "data_sources": "filename",
            "document_types": "mimetype",
            "owners": "owner",
            "connector_types": "connector_type",
        }

        filter_clauses = []
        for filter_key, values in filters.items():
            if values is None or not isinstance(values, list):
                continue

            field_name = field_mapping.get(filter_key, filter_key)
            if len(values) == 0:
                filter_clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
            elif len(values) == 1:
                filter_clauses.append({"term": {field_name: values[0]}})
            else:
                filter_clauses.append({"terms": {field_name: values}})

        return filter_clauses

    @staticmethod
    def _build_terms_agg(chunks: list[dict[str, Any]], field: str) -> Dict[str, Any]:
        counts = Counter(
            value
            for chunk in chunks
            for value in [chunk.get(field)]
            if isinstance(value, str) and value
        )
        return {
            "doc_count_error_upper_bound": 0,
            "sum_other_doc_count": 0,
            "buckets": [
                {"key": key, "doc_count": count}
                for key, count in counts.most_common()
            ],
        }

    @staticmethod
    def _build_query_for_filter_sets(
        filter_sets: list[dict[str, Any]],
        *,
        match_any: bool = True,
    ) -> dict[str, Any]:
        clauses = []
        for filter_set in filter_sets:
            if not filter_set:
                continue

            must_clauses = []
            for field_name, value in filter_set.items():
                if isinstance(value, list):
                    if len(value) == 0:
                        must_clauses.append(
                            {"term": {field_name: "__IMPOSSIBLE_VALUE__"}}
                        )
                    elif len(value) == 1:
                        must_clauses.append({"term": {field_name: value[0]}})
                    else:
                        must_clauses.append({"terms": {field_name: value}})
                else:
                    must_clauses.append({"term": {field_name: value}})

            if not must_clauses:
                continue

            clauses.append({"bool": {"must": must_clauses}})

        if not clauses:
            return {"match_none": {}}
        if len(clauses) == 1:
            return clauses[0]
        if match_any:
            return {"bool": {"should": clauses, "minimum_should_match": 1}}
        return {"bool": {"must": clauses}}

    async def index_chunks(
        self,
        chunks: list[dict[str, Any]],
        access_context: KnowledgeAccessContext,
    ) -> None:
        from utils.embedding_fields import ensure_embedding_field_exists

        if not chunks:
            return

        opensearch_client = self._get_client(access_context)
        embedding_fields_by_model: dict[str, str] = {}

        for chunk in chunks:
            metadata = chunk.get("metadata") or {}
            embedding_model = chunk.get("embedding_model") or metadata.get(
                "embedding_model"
            )
            if not embedding_model or embedding_model in embedding_fields_by_model:
                continue

            embedding = chunk.get("embedding")
            dimensions = len(embedding) if embedding else 0

            embedding_fields_by_model[embedding_model] = await ensure_embedding_field_exists(
                opensearch_client,
                embedding_model,
                get_index_name(),
                dimensions,
            )

        for chunk in chunks:
            metadata = dict(chunk.get("metadata") or {})
            body = {
                "text": chunk.get("text"),
                **metadata,
            }

            embedding_model = chunk.get("embedding_model") or metadata.get(
                "embedding_model"
            )
            embedding = chunk.get("embedding")
            if embedding_model and embedding is not None:
                body[embedding_fields_by_model[embedding_model]] = embedding

            await opensearch_client.index(
                index=get_index_name(),
                id=chunk["id"],
                body=body,
            )

    async def filename_exists(
        self,
        filename: str,
        access_context: KnowledgeAccessContext,
    ) -> bool:
        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return False

        opensearch_client = self._get_client(access_context)
        response = await opensearch_client.search(
            index=get_index_name(),
            body={
                "size": 1,
                "query": self._build_query_for_filter_sets(
                    [{"filename": candidate_filenames}]
                ),
                "_source": ["filename"],
            },
        )
        return bool(response.get("hits", {}).get("hits"))

    async def document_exists(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext,
    ) -> bool:
        if not document_id:
            return False

        opensearch_client = self._get_client(access_context)
        response = await opensearch_client.search(
            index=get_index_name(),
            body={
                "size": 1,
                "query": self._build_query_for_filter_sets(
                    [{"document_id": document_id}]
                ),
                "_source": False,
            },
        )
        return bool(response.get("hits", {}).get("hits"))

    async def delete_by_filename(
        self,
        filename: str,
        access_context: KnowledgeAccessContext,
    ) -> int:
        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return 0
        return await self.delete_by_filter_sets(
            [{"filename": candidate_filenames}],
            access_context=access_context,
            match_any=False,
        )

    async def delete_by_document_id(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext,
    ) -> int:
        if not document_id:
            return 0
        return await self.delete_by_filter_sets(
            [{"document_id": document_id}],
            access_context=access_context,
            match_any=False,
        )

    async def delete_by_filter_sets(
        self,
        filter_sets: list[dict[str, Any]],
        *,
        access_context: KnowledgeAccessContext | None = None,
        match_any: bool = True,
    ) -> int:
        if not filter_sets:
            return 0

        access_context = access_context or KnowledgeAccessContext()
        opensearch_client = self._get_client(access_context)
        result = await opensearch_client.delete_by_query(
            index=get_index_name(),
            body={"query": self._build_query_for_filter_sets(filter_sets, match_any=match_any)},
            conflicts="proceed",
        )
        return result.get("deleted", 0)

    async def list_connector_file_refs(
        self,
        connector_type: str,
        access_context: KnowledgeAccessContext,
    ) -> tuple[list[str], list[str]]:
        opensearch_client = self._get_client(access_context)
        result = await opensearch_client.search(
            index=get_index_name(),
            body={
                "size": 0,
                "query": {"term": {"connector_type": connector_type}},
                "aggs": {
                    "unique_document_ids": {
                        "terms": {"field": "document_id", "size": 10000}
                    },
                    "unique_filenames": {
                        "terms": {"field": "filename", "size": 10000}
                    },
                },
            },
        )
        doc_id_buckets = result.get("aggregations", {}).get("unique_document_ids", {}).get("buckets", [])
        filename_buckets = result.get("aggregations", {}).get("unique_filenames", {}).get("buckets", [])
        return (
            [bucket["key"] for bucket in doc_id_buckets if bucket["key"]],
            [bucket["key"] for bucket in filename_buckets if bucket["key"]],
        )

    async def refresh(self) -> None:
        await clients.opensearch.indices.refresh(index=get_index_name())

    async def search(
        self,
        *,
        query: str,
        embedding_model: str | None,
        filters: Dict[str, Any] | None,
        limit: int,
        score_threshold: float,
        access_context: KnowledgeAccessContext,
        embed_query: SearchEmbeddingFn,
    ) -> dict[str, Any]:
        from opensearchpy.exceptions import RequestError
        from utils.embedding_fields import get_embedding_field_name
        from utils.opensearch_utils import (
            DISK_SPACE_ERROR_MESSAGE,
            OpenSearchDiskSpaceError,
            is_disk_space_error,
        )

        query_embeddings = {}
        filter_clauses = self._build_filter_clauses(filters)
        available_models = []
        failed_models: list[str] = []
        is_wildcard_match_all = isinstance(query, str) and query.strip() == "*"
        resolved_embedding_model = (
            embedding_model or get_embedding_model() or OPENAI_DEFAULT_EMBEDDING_MODEL
        )

        if not access_context.user_id and access_context.enforce_acl:
            return {"results": [], "error": "Authentication required"}

        opensearch_client = self._get_client(access_context)

        if not is_wildcard_match_all:
            try:
                agg_query = {
                    "size": 0,
                    "aggs": {
                        "embedding_models": {
                            "terms": {"field": "embedding_model", "size": 10}
                        }
                    },
                }
                if filter_clauses:
                    agg_query["query"] = {"bool": {"filter": filter_clauses}}

                agg_result = await opensearch_client.search(
                    index=get_index_name(),
                    body=agg_query,
                    params={"terminate_after": 0},
                )
                buckets = agg_result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
                available_models = [bucket["key"] for bucket in buckets if bucket["key"]]
                if not available_models:
                    available_models = [resolved_embedding_model]

                logger.info(
                    "Detected embedding models in corpus",
                    available_models=available_models,
                    model_counts={bucket["key"]: bucket["doc_count"] for bucket in buckets},
                    with_filters=len(filter_clauses) > 0,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to detect embedding models, using configured model",
                    error=str(exc),
                )
                available_models = [resolved_embedding_model]

            async def embed_with_model(model_name: str):
                delay = EMBED_RETRY_INITIAL_DELAY
                attempts = 0
                last_exception = None

                while attempts < MAX_EMBED_RETRIES:
                    attempts += 1
                    try:
                        return model_name, await embed_query(query, model_name)
                    except Exception as exc:
                        last_exception = exc
                        if attempts >= MAX_EMBED_RETRIES:
                            logger.error(
                                "Failed to embed with model after retries",
                                model=model_name,
                                attempts=attempts,
                                error=str(exc),
                            )
                            raise RuntimeError(
                                f"Failed to embed with model {model_name}"
                            ) from exc

                        logger.warning(
                            "Retrying embedding generation",
                            model=model_name,
                            attempt=attempts,
                            max_attempts=MAX_EMBED_RETRIES,
                            error=str(exc),
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, EMBED_RETRY_MAX_DELAY)

                raise RuntimeError(
                    f"Failed to embed with model {model_name}"
                ) from last_exception

            embedding_results = await asyncio.gather(
                *[embed_with_model(model_name) for model_name in available_models],
                return_exceptions=True,
            )

            for model_name, result in zip(available_models, embedding_results):
                if isinstance(result, BaseException):
                    failed_models.append(model_name)
                    logger.warning(
                        "Skipping model with failed embedding; continuing with others",
                        model=model_name,
                        error=str(result),
                    )
                    continue
                if isinstance(result, tuple) and result[1] is not None:
                    successful_model, embedding = result
                    query_embeddings[successful_model] = embedding

            logger.info(
                "Generated query embeddings",
                models=list(query_embeddings.keys()),
                failed_models=failed_models,
                query_preview=query[:50],
            )

        if is_wildcard_match_all:
            if filter_clauses:
                query_block = {"bool": {"filter": filter_clauses}}
            else:
                query_block = {"match_all": {}}
        else:
            knn_queries = []
            embedding_fields_to_check = []
            for model_name, embedding_vector in query_embeddings.items():
                field_name = get_embedding_field_name(model_name)
                embedding_fields_to_check.append(field_name)
                knn_queries.append(
                    {
                        "knn": {
                            field_name: {
                                "vector": embedding_vector,
                                "k": 50,
                                "num_candidates": 1000,
                            }
                        }
                    }
                )

            all_filters = list(filter_clauses)
            if knn_queries:
                exists_should = [
                    {"exists": {"field": field_name}}
                    for field_name in embedding_fields_to_check
                ]
                if failed_models:
                    exists_should.append({"terms": {"embedding_model": failed_models}})
                all_filters.append(
                    {
                        "bool": {
                            "should": exists_should,
                            "minimum_should_match": 1,
                        }
                    }
                )

            should_clauses = []
            if knn_queries:
                should_clauses.append(
                    {
                        "dis_max": {
                            "tie_breaker": 0.0,
                            "boost": 0.7,
                            "queries": knn_queries,
                        }
                    }
                )
            should_clauses.extend(
                [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["text^2", "filename^1.5"],
                            "type": "best_fields",
                            "operator": "or",
                            "fuzziness": "AUTO:4,7",
                            "boost": 0.3 if knn_queries else 1.0,
                        }
                    },
                    {
                        "match_phrase_prefix": {
                            "text": {
                                "query": query,
                                "max_expansions": 50,
                                "boost": 0.25,
                            }
                        }
                    },
                ]
            )
            query_block = {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1,
                    "filter": all_filters,
                }
            }

        search_body = {
            "query": query_block,
            "aggs": {
                "data_sources": {"terms": {"field": "filename", "size": 20}},
                "document_types": {"terms": {"field": "mimetype", "size": 10}},
                "owners": {"terms": {"field": "owner", "size": 10}},
                "connector_types": {"terms": {"field": "connector_type", "size": 10}},
                "embedding_models": {"terms": {"field": "embedding_model", "size": 10}},
            },
            "_source": [
                "filename",
                "mimetype",
                "page",
                "text",
                "source_url",
                "owner",
                "owner_name",
                "owner_email",
                "file_size",
                "connector_type",
                "embedding_model",
                "embedding_dimensions",
                "allowed_users",
                "allowed_groups",
            ],
            "size": limit,
        }

        if not is_wildcard_match_all and score_threshold > 0:
            search_body["min_score"] = score_threshold

        fallback_search_body = None
        if not is_wildcard_match_all and query_embeddings:
            try:
                fallback_search_body = copy.deepcopy(search_body)
                knn_query_blocks = fallback_search_body["query"]["bool"]["should"][0]["dis_max"]["queries"]
                for query_candidate in knn_query_blocks:
                    knn_section = query_candidate.get("knn")
                    if isinstance(knn_section, dict):
                        for params in knn_section.values():
                            if isinstance(params, dict):
                                params.pop("num_candidates", None)
            except (KeyError, IndexError, AttributeError, TypeError):
                fallback_search_body = None

        search_params = {"terminate_after": 0}
        try:
            results = await opensearch_client.search(
                index=get_index_name(),
                body=search_body,
                params=search_params,
            )
        except RequestError as exc:
            error_message = str(exc)
            if is_disk_space_error(exc):
                raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from exc
            if (
                fallback_search_body is not None
                and "unknown field [num_candidates]" in error_message.lower()
            ):
                results = await opensearch_client.search(
                    index=get_index_name(),
                    body=fallback_search_body,
                    params=search_params,
                )
            else:
                raise
        except OpenSearchDiskSpaceError:
            raise
        except Exception as exc:
            if is_disk_space_error(exc):
                raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from exc
            raise

        chunks = []
        for hit in results["hits"]["hits"]:
            source = hit.get("_source", {})
            chunks.append(
                {
                    "filename": source.get("filename"),
                    "mimetype": source.get("mimetype"),
                    "page": source.get("page"),
                    "text": source.get("text"),
                    "score": hit.get("_score"),
                    "source_url": source.get("source_url"),
                    "owner": source.get("owner"),
                    "owner_name": source.get("owner_name"),
                    "owner_email": source.get("owner_email"),
                    "file_size": source.get("file_size"),
                    "connector_type": source.get("connector_type"),
                    "embedding_model": source.get("embedding_model"),
                    "embedding_dimensions": source.get("embedding_dimensions"),
                    "allowed_users": source.get("allowed_users", []),
                    "allowed_groups": source.get("allowed_groups", []),
                }
            )

        normalized_query = query.strip().lower()
        aggregations = results.get("aggregations", {})
        if normalized_query and not is_wildcard_match_all and len(normalized_query) >= 4:
            exact_files = {
                filename
                for chunk in chunks
                for filename in [chunk.get("filename")]
                if isinstance(filename, str)
                and (
                    normalized_query in filename.lower()
                    or (
                        isinstance(chunk.get("text"), str)
                        and normalized_query in chunk.get("text", "").lower()
                    )
                )
            }
            if exact_files:
                chunks = [
                    chunk for chunk in chunks if chunk.get("filename") in exact_files
                ]
                aggregations = {
                    **aggregations,
                    "data_sources": self._build_terms_agg(chunks, "filename"),
                    "document_types": self._build_terms_agg(chunks, "mimetype"),
                    "owners": self._build_terms_agg(chunks, "owner"),
                    "connector_types": self._build_terms_agg(chunks, "connector_type"),
                    "embedding_models": self._build_terms_agg(chunks, "embedding_model"),
                }

        response: Dict[str, Any] = {
            "results": chunks,
            "aggregations": aggregations,
            "total": len(chunks),
        }
        if failed_models:
            response["warnings"] = [
                {
                    "code": "embedding_unavailable",
                    "models": failed_models,
                    "semantic_search_available": bool(query_embeddings),
                    "message": (
                        "Some documents were embedded with models that are "
                        "no longer reachable (provider removed or misconfigured). "
                        "Results shown use keyword matching only for those models."
                        if not query_embeddings
                        else "Semantic search is degraded for some embedding models."
                    ),
                }
            ]
        return response


def get_knowledge_backend_service(session_manager=None) -> KnowledgeBackend:
    backend = get_configured_knowledge_backend()
    if backend == "astra":
        from services.astra_db_service import AstraDBService

        return AstraDBService()
    return OpenSearchKnowledgeBackend(session_manager)
