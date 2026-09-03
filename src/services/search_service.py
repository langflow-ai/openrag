import asyncio
import copy
import os
import re
from collections import Counter
from typing import Any

from agentd.tool_decorator import tool

from auth_context import get_auth_context
from config.embedding_constants import get_declared_default_embedding_model
from config.settings import get_embedding_model, get_index_name, get_openrag_config
from services.llm_gateway import LlmGatewayError
from services.llm_gateway import embeddings as gateway_embeddings
from utils.container_utils import transform_localhost_url
from utils.embedding_fields import (
    INDEXED_EMBEDDING_ROUTE_PREFIX,
    EmbeddingSpace,
    build_embedding_space_aggregation,
    embedding_space_after_keys,
    embedding_spaces_from_aggregation,
    get_embedding_field_name,
    get_embedding_space_id,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0
EMBEDDING_SPACE_PAGE_SIZE = 100


# Variable used to store the active instance for the tool wrapper
_global_search_service = None


def _is_exact_token_query(query: str) -> bool:
    """Return True for code/token-like queries (identifiers, versions, SKUs)
    that warrant exact-file narrowing; ordinary prose returns False."""
    query = query.strip()
    if not query or len(query) < 3:
        return False

    if re.search(r"[^a-zA-Z0-9\s]", query):
        return True

    return bool(re.search(r"[a-zA-Z]", query) and re.search(r"\d", query))


def _build_file_facet_aggregations(size_overrides: dict[str, int] | None = None) -> dict[str, Any]:
    size_overrides = size_overrides or {}
    facet_fields = {
        "data_sources": "filename",
        "document_types": "mimetype",
        "owners": "owner",
        "connector_types": "connector_type",
        "embedding_models": "embedding_model",
    }

    aggregations: dict[str, Any] = {}
    for facet_name, field_name in facet_fields.items():
        agg: dict[str, Any] = {
            "terms": {
                "field": field_name,
                "size": size_overrides.get(facet_name, 1000),
            },
        }
        if facet_name == "owners":
            agg["aggs"] = {
                "files": {"cardinality": {"field": "filename"}},
                "owner_metadata": {
                    "top_hits": {
                        "size": 1,
                        "_source": {
                            "includes": ["owner_name", "owner_email", "owner"],
                        },
                    }
                },
            }
        elif facet_name != "data_sources":
            agg["aggs"] = {"files": {"cardinality": {"field": "filename"}}}
        aggregations[facet_name] = agg
    return aggregations


def _normalize_file_facet_aggregations(aggregations: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(aggregations)
    for facet_name in (
        "data_sources",
        "document_types",
        "owners",
        "connector_types",
        "embedding_models",
    ):
        facet = aggregations.get(facet_name)
        if not isinstance(facet, dict):
            normalized[facet_name] = {"buckets": []}
            continue

        raw_buckets = facet.get("buckets", [])
        buckets = raw_buckets if isinstance(raw_buckets, list) else []
        normalized_buckets: list[dict[str, Any]] = []
        for bucket in buckets:
            if not isinstance(bucket, dict) or not bucket.get("key"):
                continue

            normalized_bucket = {"key": bucket.get("key")}
            if facet_name == "owners":
                owner_hits = bucket.get("owner_metadata", {}).get("hits", {}).get("hits", [])
                owner_source = owner_hits[0].get("_source", {}) if owner_hits else {}
                normalized_bucket["label"] = (
                    owner_source.get("owner_name")
                    or owner_source.get("owner_email")
                    or bucket.get("key")
                )

            if facet_name != "data_sources":
                normalized_bucket["doc_count"] = bucket.get("files", {}).get(
                    "value", bucket.get("doc_count", 0)
                )

            normalized_buckets.append(normalized_bucket)

        normalized[facet_name] = {
            **facet,
            "buckets": normalized_buckets,
        }
    return normalized


def _apply_exact_match_file_filter(
    query: str,
    chunks: list[dict[str, Any]],
    aggregations: dict[str, Any],
    *,
    is_wildcard_match_all: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """If a token-like query appears verbatim in a subset of files, prefer those files.

    This avoids broad semantic spillover for unique lookups. Narrowing only
    applies to token-like queries (see _is_exact_token_query); multi-word prose
    searches keep their full hybrid-ranked results. When no file contains the
    query verbatim, the ranked results are returned untouched — hits must never
    be discarded just because the query looks token-like (e.g. "chunk_overlap",
    "v1.2", "SKU-1234").
    """
    normalized_query = query.strip().lower()
    if (
        not normalized_query
        or is_wildcard_match_all
        or len(normalized_query) < 4
        or not _is_exact_token_query(normalized_query)
    ):
        return chunks, aggregations

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
    if not exact_files:
        return chunks, aggregations

    # Filter to only chunks from files with exact matches
    chunks = [chunk for chunk in chunks if chunk.get("filename") in exact_files]

    def _build_terms_agg(field: str, label_field: str | None = None) -> dict[str, Any]:
        file_counts: Counter[Any] = Counter()
        labels_by_value: dict[str, str] = {}
        for chunk in chunks:
            value = chunk.get(field)
            filename = chunk.get("filename")
            if not isinstance(value, str) or not value:
                continue
            if not isinstance(filename, str) or not filename:
                continue
            file_counts[(value, filename)] += 1
            if label_field and value not in labels_by_value:
                label = chunk.get(label_field)
                if isinstance(label, str) and label:
                    labels_by_value[value] = label

        counts = Counter(value for value, _filename in file_counts)
        return {
            "doc_count_error_upper_bound": 0,
            "sum_other_doc_count": 0,
            "buckets": [
                {
                    "key": key,
                    "doc_count": count,
                    **({"label": labels_by_value.get(key, key)} if label_field else {}),
                }
                for key, count in counts.most_common()
            ],
        }

    # Keep aggregations consistent with the post-filtered result set.
    aggregations = {
        **aggregations,
        "data_sources": _build_terms_agg("filename"),
        "document_types": _build_terms_agg("mimetype"),
        "owners": _build_terms_agg("owner", label_field="owner_name"),
        "connector_types": _build_terms_agg("connector_type"),
        "embedding_models": _build_terms_agg("embedding_model"),
    }
    return chunks, aggregations


def register_search_service(service: "SearchService") -> None:
    """
    Explicitly register the active search service for the @tool wrapper.
    This prevents stale instance risks and test interference.
    """
    global _global_search_service
    _global_search_service = service


@tool
async def search_tool(query: str, embedding_model: str = None) -> dict[str, Any]:
    """
    Use this tool to search for documents relevant to the query.

    Args:
        query (str): query string to search the corpus
        embedding_model (str): Optional override for embedding model.
                              If not provided, uses the current embedding
                              model from configuration.

    Returns:
        dict (str, Any): {"results": [chunks]} on success
    """
    if not _global_search_service:
        logger.error("SearchService tool called before initialization")
        return {"results": [], "error": "Search service not available"}
    return await _global_search_service.search_tool(query, embedding_model=embedding_model)


class SearchService:
    def __init__(self, session_manager=None, models_service=None):
        self.session_manager = session_manager
        self.models_service = models_service
        self._configure_provider_env()

    def _configure_provider_env(self):
        """Set provider env vars once at init time."""
        try:
            config = get_openrag_config()
            if config.providers.ollama.endpoint:
                fixed = transform_localhost_url(config.providers.ollama.endpoint)
                # Use setdefault to avoid clobbering existing env vars if they were
                # set explicitly via shell, but ensures we have a working default.
                os.environ.setdefault("OLLAMA_API_BASE", fixed)
                os.environ.setdefault("OLLAMA_BASE_URL", fixed)
        except Exception as e:
            logger.warning("[SEARCH] Could not configure Ollama endpoint from config", error=str(e))

    async def search_tool(
        self,
        query: str,
        embedding_model: str = None,
        *,
        exclude_sample_data: bool = False,
    ) -> dict[str, Any]:
        """
        Use this tool to search for documents relevant to the query.

        Args:
            query (str): query string to search the corpus
            embedding_model (str): Optional override for embedding model.
                                  If not provided, uses the current embedding
                                  model from configuration.
            exclude_sample_data (bool): Drop chunks indexed from the bundled
                                  sample corpus. Off by default; used by nudge
                                  generation when no user filters are active.

        Returns:
            dict (str, Any): {"results": [chunks]} on success
        """
        # Strategy: Use provided model, or default to the configured embedding
        # model. This assumes documents are embedded with that model by default.
        # Future enhancement: Could auto-detect available models in corpus.
        embedding_model = (
            embedding_model
            or get_embedding_model()
            or get_declared_default_embedding_model(
                get_openrag_config().knowledge.embedding_provider
            )
        )
        embedding_field_name = get_embedding_field_name(embedding_model)

        logger.info(
            "[SEARCH] Query started",
            embedding_model=embedding_model,
            embedding_field=embedding_field_name,
            query_preview=query[:50] if query else None,
        )

        # Get authentication context from the current async context
        user_id, jwt_token = get_auth_context()
        # Get search filters, limit, and score threshold from context
        from auth_context import (
            get_score_threshold,
            get_search_filters,
            get_search_limit,
        )

        filters = get_search_filters() or {}
        limit = get_search_limit()
        score_threshold = get_score_threshold()
        # Detect wildcard request ("*") to return global facets/stats without semantic search
        is_wildcard_match_all = isinstance(query, str) and query.strip() == "*"

        # Get available embedding models from corpus
        query_embeddings = {}
        available_spaces: list[EmbeddingSpace] = []
        failed_models: list = []

        opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)

        if not is_wildcard_match_all:
            # Build filter clauses first so we can use them in model detection
            filter_clauses: list[dict[str, Any]] = []
            if filters:
                # Map frontend filter names to backend field names
                field_mapping = {
                    "data_sources": "filename",
                    "document_types": "mimetype",
                    "owners": "owner",
                    "connector_types": "connector_type",
                }

                for filter_key, values in filters.items():
                    if values is not None and isinstance(values, list):
                        # Map frontend key to backend field name
                        field_name = field_mapping.get(filter_key, filter_key)

                        if len(values) == 0:
                            # Empty array means "match nothing" - use impossible filter
                            filter_clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
                        elif len(values) == 1:
                            # Single value filter
                            filter_clauses.append({"term": {field_name: values[0]}})
                        else:
                            # Multiple values filter
                            filter_clauses.append({"terms": {field_name: values}})

            try:
                seen_spaces: set[str] = set()
                for legacy in (False, True):
                    after = None
                    while True:
                        agg_query = {
                            "size": 0,
                            "aggs": build_embedding_space_aggregation(
                                size=EMBEDDING_SPACE_PAGE_SIZE,
                                qualified_after=None if legacy else after,
                                legacy_after=after if legacy else None,
                                include_qualified=not legacy,
                                include_legacy=legacy,
                            ),
                        }
                        bool_query: dict[str, Any] = {}
                        if filter_clauses:
                            bool_query["filter"] = filter_clauses
                        if legacy:
                            bool_query["must_not"] = [{"exists": {"field": "embedding_space_id"}}]
                        if bool_query:
                            agg_query["query"] = {"bool": bool_query}

                        agg_result = await opensearch_client.search(
                            index=get_index_name(), body=agg_query, params={"terminate_after": 0}
                        )
                        for space in embedding_spaces_from_aggregation(agg_result):
                            if space.space_id not in seen_spaces:
                                seen_spaces.add(space.space_id)
                                available_spaces.append(space)

                        qualified_after, legacy_after = embedding_space_after_keys(agg_result)
                        next_after = legacy_after if legacy else qualified_after
                        if not next_after or next_after == after:
                            break
                        after = next_after

                if not available_spaces:
                    # Fallback to configured model if no documents indexed yet
                    provider = get_openrag_config().knowledge.embedding_provider or "openai"
                    if embedding_model:
                        space_id = get_embedding_space_id(provider, embedding_model)
                        available_spaces = [
                            EmbeddingSpace(
                                space_id=space_id,
                                route_model=f"{INDEXED_EMBEDDING_ROUTE_PREFIX}{space_id}",
                                field_identity=space_id,
                            )
                        ]

                logger.info(
                    "Detected embedding spaces in corpus",
                    available_spaces=[space.space_id for space in available_spaces],
                    with_filters=len(filter_clauses) > 0,
                )
            except Exception as e:
                logger.warning(
                    "Failed to detect embedding spaces, using configured model", error=str(e)
                )
                provider = get_openrag_config().knowledge.embedding_provider or "openai"
                if embedding_model:
                    space_id = get_embedding_space_id(provider, embedding_model)
                    available_spaces = [
                        EmbeddingSpace(
                            space_id=space_id,
                            route_model=f"{INDEXED_EMBEDDING_ROUTE_PREFIX}{space_id}",
                            field_identity=space_id,
                        )
                    ]

            # Parallelize embedding generation for all models
            async def embed_with_space(
                space: EmbeddingSpace,
            ) -> tuple[EmbeddingSpace, list[float]]:
                """Generate one query vector through its exact gateway route."""
                delay = EMBED_RETRY_INITIAL_DELAY
                attempts = 0
                last_exception = None

                while attempts < MAX_EMBED_RETRIES:
                    attempts += 1
                    try:
                        # Use the same credential-aware gateway as Langflow.
                        # Provider-qualified and legacy routes are resolved in
                        # one place and upstream credentials never leave OpenRAG.
                        resp = await gateway_embeddings(
                            {"model": space.route_model, "input": [query]}
                        )
                        data = resp.get("data", [])
                        embedding = data[0].get("embedding") if data else None
                        if embedding is None:
                            raise RuntimeError("Embedding provider returned no vector")
                        return space, embedding
                    except LlmGatewayError:
                        # Configuration/provenance errors are deterministic;
                        # skip this space immediately and retain keyword search.
                        raise
                    except Exception as e:
                        last_exception = e
                        if attempts >= MAX_EMBED_RETRIES:
                            logger.error(
                                "Failed to embed with model after retries",
                                model=space.space_id,
                                attempts=attempts,
                                error=str(e),
                            )
                            raise RuntimeError(
                                f"Failed to embed with model {space.space_id}"
                            ) from e

                        logger.warning(
                            "Retrying embedding generation",
                            model=space.space_id,
                            attempt=attempts,
                            max_attempts=MAX_EMBED_RETRIES,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, EMBED_RETRY_MAX_DELAY)

                # Should not reach here, but guard in case
                raise RuntimeError(
                    f"Failed to embed with model {space.space_id}"
                ) from last_exception

            # Run all embeddings in parallel, tolerating per-model failures so
            # one broken model (e.g. provider credentials removed after ingest)
            # doesn't take down the entire search. If all models fail we fall
            # back to keyword-only search below.
            embedding_results = await asyncio.gather(
                *[embed_with_space(space) for space in available_spaces],
                return_exceptions=True,
            )

            for space, result in zip(available_spaces, embedding_results, strict=False):
                if isinstance(result, BaseException):
                    failed_models.append(space.space_id)
                    logger.warning(
                        "Skipping model with failed embedding; continuing with others",
                        model=space.space_id,
                        error=str(result),
                    )
                    continue
                if isinstance(result, tuple) and result[1] is not None:
                    successful_space, embedding = result
                    query_embeddings[successful_space.field_identity] = embedding

            logger.info(
                "Generated query embeddings",
                models=list(query_embeddings.keys()),
                failed_models=failed_models,
                query_preview=query[:50],
            )
        else:
            # Wildcard query - no embedding needed
            filter_clauses = []
            if filters:
                # Map frontend filter names to backend field names
                field_mapping = {
                    "data_sources": "filename",
                    "document_types": "mimetype",
                    "owners": "owner",
                    "connector_types": "connector_type",
                }

                for filter_key, values in filters.items():
                    if values is not None and isinstance(values, list):
                        # Map frontend key to backend field name
                        field_name = field_mapping.get(filter_key, filter_key)

                        if len(values) == 0:
                            # Empty array means "match nothing" - use impossible filter
                            filter_clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
                        elif len(values) == 1:
                            # Single value filter
                            filter_clauses.append({"term": {field_name: values[0]}})
                        else:
                            # Multiple values filter
                            filter_clauses.append({"terms": {field_name: values}})

        # Sample docs are onboarding filler; nudges built from them describe the
        # demo corpus rather than the user's own. Both branches above have
        # populated filter_clauses by now, so this covers wildcard and hybrid.
        if exclude_sample_data:
            filter_clauses.append({"bool": {"must_not": [{"term": {"is_sample_data": "true"}}]}})

        # Build query body
        if is_wildcard_match_all:
            # Match all documents; still allow filters to narrow scope
            if filter_clauses:
                query_block: dict[str, Any] = {"bool": {"filter": filter_clauses}}
            else:
                query_block = {"match_all": {}}
        else:
            # Build multi-model KNN queries (only for models that successfully
            # produced query embeddings)
            knn_queries = []
            for field_identity, embedding_vector in query_embeddings.items():
                field_name = get_embedding_field_name(field_identity)
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

            # KNN clauses naturally apply only to documents carrying their
            # vector field. Keep all other documents eligible for keyword
            # matching, including unresolved legacy provider spaces.
            all_filters = list(filter_clauses)

            logger.debug(
                "Building hybrid query with filters",
                user_filters_count=len(filter_clauses),
                total_filters_count=len(all_filters),
                filter_types=[type(f).__name__ for f in all_filters],
                knn_queries_count=len(knn_queries),
            )

            # Hybrid search (semantic + keyword) when embeddings are available;
            # keyword-only fallback when none succeeded. When falling back, bump
            # the multi_match boost so keyword scoring isn't artificially damped.
            should_clauses = []
            if knn_queries:
                should_clauses.append(
                    {
                        "dis_max": {
                            "tie_breaker": 0.0,  # Take only the best match, no blending
                            "boost": 0.7,  # 70% weight for semantic search
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
                        # Prefix fallback for partial input (e.g. "vita" -> "vitamin").
                        # Avoid bool_prefix here because our current mappings are:
                        # - text: standard "text" (not search_as_you_type / edge-ngram)
                        # - filename: "keyword"
                        # match_phrase_prefix with a bounded expansion is safer.
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

        search_body: dict[str, Any] = {
            "query": query_block,
            "aggs": _build_file_facet_aggregations(),
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
                "embedding_model",  # Include embedding model in results
                "embedding_provider",
                "embedding_space_id",
                "embedding_dimensions",
                "parser",
                "chunk_size",
                "chunk_overlap",
                "allowed_users",
                "allowed_groups",
                "allowed_principal_labels",
            ],
            "size": limit,
        }

        # Add score threshold only for hybrid (not meaningful for match_all)
        if not is_wildcard_match_all and score_threshold > 0:
            search_body["min_score"] = score_threshold

        # Prepare fallback search body without num_candidates for clusters that don't support it.
        # Only relevant when we actually dispatched KNN queries.
        fallback_search_body: dict[str, Any] | None = None
        if not is_wildcard_match_all and query_embeddings:
            try:
                fallback_search_body = copy.deepcopy(search_body)
                knn_query_blocks = fallback_search_body["query"]["bool"]["should"][0]["dis_max"][
                    "queries"
                ]
                for query_candidate in knn_query_blocks:
                    knn_section = query_candidate.get("knn")
                    if isinstance(knn_section, dict):
                        for params in knn_section.values():
                            if isinstance(params, dict):
                                params.pop("num_candidates", None)
            except (KeyError, IndexError, AttributeError, TypeError):
                fallback_search_body = None

        # Authentication required - ACL filter is applied at the application layer above
        logger.debug(
            "search_service authentication info",
            user_id=user_id,
            has_jwt_token=jwt_token is not None,
        )
        if not user_id:
            logger.warning("[SEARCH] user_id missing, rejecting search request")
            return {"results": [], "error": "Authentication required"}

        # Get user's OpenSearch client with JWT for OIDC auth through session manager
        opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)

        from opensearchpy.exceptions import RequestError

        from utils.opensearch_utils import (
            DISK_SPACE_ERROR_MESSAGE,
            OpenSearchDiskSpaceError,
            is_disk_space_error,
        )

        search_params = {"terminate_after": 0}

        try:
            index_name = get_index_name()
            logger.info(f"Sending query to index '{index_name}'..")
            results = await opensearch_client.search(
                index=index_name, body=search_body, params=search_params
            )
        except RequestError as e:
            error_message = str(e)
            if is_disk_space_error(e):
                logger.error(
                    "OpenSearch query blocked by disk space constraint",
                    error=error_message,
                )
                raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from e
            if (
                fallback_search_body is not None
                and "unknown field [num_candidates]" in error_message.lower()
            ):
                logger.warning(
                    "OpenSearch cluster does not support num_candidates; retrying without it"
                )
                try:
                    results = await opensearch_client.search(
                        index=get_index_name(),
                        body=fallback_search_body,
                        params=search_params,
                    )
                except RequestError as retry_error:
                    if is_disk_space_error(retry_error):
                        logger.error(
                            "OpenSearch retry blocked by disk space constraint",
                            error=str(retry_error),
                        )
                        raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from retry_error
                    logger.error(
                        "OpenSearch retry without num_candidates failed",
                        error=str(retry_error),
                        search_body=fallback_search_body,
                    )
                    raise
            else:
                logger.error(
                    "OpenSearch query failed", error=error_message, search_body=search_body
                )
                raise
        except OpenSearchDiskSpaceError:
            raise
        except Exception as e:
            if is_disk_space_error(e):
                logger.error(
                    "OpenSearch query blocked by disk space constraint",
                    error=str(e),
                )
                raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from e
            logger.error("OpenSearch query failed", error=str(e), search_body=search_body)
            # Re-raise the exception so the API returns the error to frontend
            raise

        # Transform results (keep for backward compatibility)
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
                    "embedding_model": source.get("embedding_model"),  # Include in results
                    "embedding_provider": source.get("embedding_provider"),
                    "embedding_space_id": source.get("embedding_space_id"),
                    "embedding_dimensions": source.get("embedding_dimensions"),
                    "parser": source.get("parser"),
                    "chunk_size": source.get("chunk_size"),
                    "chunk_overlap": source.get("chunk_overlap"),
                    "chunk_id": hit.get("_id"),
                    "id": hit.get("_id"),
                    # ACL fields (may be missing for some documents)
                    "allowed_users": source.get("allowed_users", []),
                    "allowed_groups": source.get("allowed_groups", []),
                    "allowed_principal_labels": source.get("allowed_principal_labels", []),
                }
            )

        # If query text appears verbatim in one subset of files, prefer those files
        # to avoid broad semantic spillover for unique lookups.
        chunks, aggregations = _apply_exact_match_file_filter(
            query,
            chunks,
            _normalize_file_facet_aggregations(results.get("aggregations", {})),
            is_wildcard_match_all=is_wildcard_match_all,
        )

        # Return both transformed results and aggregations. Surface degraded
        # semantic-search signals so the UI can show a non-fatal warning
        # instead of treating partial-embedding failure as a hard error.
        response: dict[str, Any] = {
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

    async def search(
        self,
        query: str,
        user_id: str = None,
        jwt_token: str = None,
        filters: dict[str, Any] = None,
        limit: int = 10,
        score_threshold: float = 0,
        embedding_model: str = None,
        exclude_sample_data: bool = False,
    ) -> dict[str, Any]:
        """Public search method for API endpoints

        Args:
            embedding_model: Embedding model to use for search (defaults to the
                currently configured embedding model)
        """
        # Set auth context if provided (for direct API calls)
        from config.settings import is_no_auth_mode

        if user_id and (jwt_token or is_no_auth_mode()):
            from auth_context import set_auth_context

            set_auth_context(user_id, jwt_token)

        # Set filters and limit in context if provided
        if filters:
            from auth_context import set_search_filters

            set_search_filters(filters)

        from auth_context import set_score_threshold, set_search_limit

        set_search_limit(limit)
        set_score_threshold(score_threshold)

        return await self.search_tool(
            query, embedding_model=embedding_model, exclude_sample_data=exclude_sample_data
        )
