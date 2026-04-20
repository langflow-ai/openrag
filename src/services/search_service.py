import asyncio
import copy
import os
import json
from collections import Counter
from typing import Any, Dict
from agentd.tool_decorator import tool
from config.settings import clients, get_embedding_model, get_index_name, get_openrag_config
from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
from utils.container_utils import transform_localhost_url
from auth_context import get_auth_context
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0


# Variable used to store the active instance for the tool wrapper
_global_search_service = None


def register_search_service(service: "SearchService") -> None:
    """
    Explicitly register the active search service for the @tool wrapper.
    This prevents stale instance risks and test interference.
    """
    global _global_search_service
    _global_search_service = service


@tool
async def search_tool(query: str, embedding_model: str = None) -> Dict[str, Any]:
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
            logger.debug("Could not configure Ollama endpoint from config", error=str(e))

    async def search_tool(self, query: str, embedding_model: str = None) -> Dict[str, Any]:
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
        from utils.embedding_fields import get_embedding_field_name

        # Strategy: Use provided model, or default to the configured embedding
        # model. This assumes documents are embedded with that model by default.
        # Future enhancement: Could auto-detect available models in corpus.
        embedding_model = embedding_model or get_embedding_model() or OPENAI_DEFAULT_EMBEDDING_MODEL
        embedding_field_name = get_embedding_field_name(embedding_model)

        logger.info(
            "Search with embedding model",
            embedding_model=embedding_model,
            embedding_field=embedding_field_name,
            query_preview=query[:50] if query else None,
        )

        # Get authentication context from the current async context
        user_id, jwt_token = get_auth_context()
        # Get search filters, limit, and score threshold from context
        from auth_context import (
            get_search_filters,
            get_search_limit,
            get_score_threshold,
        )

        filters = get_search_filters() or {}
        limit = get_search_limit()
        score_threshold = get_score_threshold()
        # Detect wildcard request ("*") to return global facets/stats without semantic search
        is_wildcard_match_all = isinstance(query, str) and query.strip() == "*"

        # Get available embedding models from corpus
        query_embeddings = {}
        available_models = []

        opensearch_client = self.session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )

        if not is_wildcard_match_all:
            # Build filter clauses first so we can use them in model detection
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
                            filter_clauses.append(
                                {"term": {field_name: "__IMPOSSIBLE_VALUE__"}}
                            )
                        elif len(values) == 1:
                            # Single value filter
                            filter_clauses.append({"term": {field_name: values[0]}})
                        else:
                            # Multiple values filter
                            filter_clauses.append({"terms": {field_name: values}})

            try:
                # Build aggregation query with filters applied
                agg_query = {
                    "size": 0,
                    "aggs": {
                        "embedding_models": {
                            "terms": {
                                "field": "embedding_model",
                                "size": 10
                            }
                        }
                    }
                }

                # Apply filters to model detection if any exist
                if filter_clauses:
                    agg_query["query"] = {
                        "bool": {
                            "filter": filter_clauses
                        }
                    }

                agg_result = await opensearch_client.search(
                    index=get_index_name(), body=agg_query, params={"terminate_after": 0}
                )
                buckets = agg_result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
                available_models = [b["key"] for b in buckets if b["key"]]

                if not available_models:
                    # Fallback to configured model if no documents indexed yet
                    available_models = [embedding_model]

                logger.info(
                    "Detected embedding models in corpus",
                    available_models=available_models,
                    model_counts={b["key"]: b["doc_count"] for b in buckets},
                    with_filters=len(filter_clauses) > 0
                )
            except Exception as e:
                logger.warning("Failed to detect embedding models, using configured model", error=str(e))
                available_models = [embedding_model]

            # Parallelize embedding generation for all models
            async def embed_with_model(model_name):
                delay = EMBED_RETRY_INITIAL_DELAY
                attempts = 0
                last_exception = None

                # Use centralized utility for LiteLLM model formatting
                if self.models_service:
                    formatted_model = await self.models_service.get_litellm_model_name(model_name)
                else:
                    # Fallback if service not injected (tests/etc)
                    formatted_model = model_name

                while attempts < MAX_EMBED_RETRIES:
                    attempts += 1
                    try:
                        resp = await clients.patched_embedding_client.embeddings.create(
                            model=formatted_model, input=[query]
                        )
                        # Try to get embedding - some providers return .embedding, others return ['embedding']
                        embedding = getattr(resp.data[0], 'embedding', None)
                        if embedding is None:
                            embedding = resp.data[0]['embedding']
                        return model_name, embedding
                    except Exception as e:
                        last_exception = e
                        if attempts >= MAX_EMBED_RETRIES:
                            logger.error(
                                "Failed to embed with model after retries",
                                model=model_name,
                                attempts=attempts,
                                error=str(e),
                            )
                            raise RuntimeError(
                                f"Failed to embed with model {model_name}"
                            ) from e

                        logger.warning(
                            "Retrying embedding generation",
                            model=model_name,
                            attempt=attempts,
                            max_attempts=MAX_EMBED_RETRIES,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, EMBED_RETRY_MAX_DELAY)

                # Should not reach here, but guard in case
                raise RuntimeError(
                    f"Failed to embed with model {model_name}"
                ) from last_exception

            # Run all embeddings in parallel
            try:
                embedding_results = await asyncio.gather(
                    *[embed_with_model(model) for model in available_models]
                )
            except Exception as e:
                logger.error("Embedding generation failed", error=str(e))
                raise

            # Collect successful embeddings
            for result in embedding_results:
                if isinstance(result, tuple) and result[1] is not None:
                    model_name, embedding = result
                    query_embeddings[model_name] = embedding

            logger.info(
                "Generated query embeddings",
                models=list(query_embeddings.keys()),
                query_preview=query[:50]
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
                            filter_clauses.append(
                                {"term": {field_name: "__IMPOSSIBLE_VALUE__"}}
                            )
                        elif len(values) == 1:
                            # Single value filter
                            filter_clauses.append({"term": {field_name: values[0]}})
                        else:
                            # Multiple values filter
                            filter_clauses.append({"terms": {field_name: values}})

        # Build query body
        if is_wildcard_match_all:
            # Match all documents; still allow filters to narrow scope
            if filter_clauses:
                query_block = {"bool": {"filter": filter_clauses}}
            else:
                query_block = {"match_all": {}}
        else:
            # Build multi-model KNN queries
            knn_queries = []
            embedding_fields_to_check = []

            for model_name, embedding_vector in query_embeddings.items():
                field_name = get_embedding_field_name(model_name)
                embedding_fields_to_check.append(field_name)
                knn_queries.append({
                    "knn": {
                        field_name: {
                            "vector": embedding_vector,
                            "k": 50,
                            "num_candidates": 1000,
                        }
                    }
                })

            # Build exists filter - doc must have at least one embedding field
            exists_any_embedding = {
                "bool": {
                    "should": [{"exists": {"field": f}} for f in embedding_fields_to_check],
                    "minimum_should_match": 1
                }
            }

            # Add exists filter to existing filters
            all_filters = [*filter_clauses, exists_any_embedding]

            logger.debug(
                "Building hybrid query with filters",
                user_filters_count=len(filter_clauses),
                total_filters_count=len(all_filters),
                filter_types=[type(f).__name__ for f in all_filters]
            )

            # Hybrid search query structure (semantic + keyword)
            # Use dis_max to pick best score across multiple embedding fields
            query_block = {
                "bool": {
                    "should": [
                        {
                            "dis_max": {
                                "tie_breaker": 0.0,  # Take only the best match, no blending
                                "boost": 0.7,         # 70% weight for semantic search
                                "queries": knn_queries
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["text^2", "filename^1.5"],
                                "type": "best_fields",
                                "operator": "or",
                                "fuzziness": "AUTO:4,7",
                                "boost": 0.3,  # 30% weight for keyword search
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
                    ],
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
                "embedding_model",  # Include embedding model in results
                "embedding_dimensions",
                "allowed_users",
                "allowed_groups",
            ],
            "size": limit,
        }

        # Add score threshold only for hybrid (not meaningful for match_all)
        if not is_wildcard_match_all and score_threshold > 0:
            search_body["min_score"] = score_threshold

        # Prepare fallback search body without num_candidates for clusters that don't support it
        fallback_search_body = None
        if not is_wildcard_match_all:
            try:
                fallback_search_body = copy.deepcopy(search_body)
                knn_query_blocks = (
                    fallback_search_body["query"]["bool"]["should"][0]["dis_max"]["queries"]
                )
                for query_candidate in knn_query_blocks:
                    knn_section = query_candidate.get("knn")
                    if isinstance(knn_section, dict):
                        for params in knn_section.values():
                            if isinstance(params, dict):
                                params.pop("num_candidates", None)
            except (KeyError, IndexError, AttributeError, TypeError):
                fallback_search_body = None

        # Authentication required - DLS will handle document filtering automatically
        logger.debug(
            "search_service authentication info",
            user_id=user_id,
            has_jwt_token=jwt_token is not None,
        )
        if not user_id:
            logger.debug("search_service: user_id is None/empty, returning auth error")
            return {"results": [], "error": "Authentication required"}

        # Get user's OpenSearch client with JWT for OIDC auth through session manager
        opensearch_client = self.session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )

        from opensearchpy.exceptions import RequestError
        from utils.opensearch_utils import OpenSearchDiskSpaceError, is_disk_space_error, DISK_SPACE_ERROR_MESSAGE

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
            logger.error(
                "OpenSearch query failed", error=str(e), search_body=search_body
            )
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
                    "embedding_dimensions": source.get("embedding_dimensions"),
                    # ACL fields (may be missing for some documents)
                    "allowed_users": source.get("allowed_users", []),
                    "allowed_groups": source.get("allowed_groups", []),
                }
            )

        # If query text appears verbatim in one subset of files, prefer those files
        # to avoid broad semantic spillover for unique lookups.
        normalized_query = query.strip().lower()
        aggregations = results.get("aggregations", {})
        if (
            normalized_query
            and not is_wildcard_match_all
            and len(normalized_query) >= 4
        ):
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
                chunks = [chunk for chunk in chunks if chunk.get("filename") in exact_files]

                def _build_terms_agg(field: str) -> Dict[str, Any]:
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

                # Keep aggregations consistent with the post-filtered result set.
                aggregations = {
                    **aggregations,
                    "data_sources": _build_terms_agg("filename"),
                    "document_types": _build_terms_agg("mimetype"),
                    "owners": _build_terms_agg("owner"),
                    "connector_types": _build_terms_agg("connector_type"),
                    "embedding_models": _build_terms_agg("embedding_model"),
                }

        # Return both transformed results and aggregations
        return {
            "results": chunks,
            "aggregations": aggregations,
            "total": len(chunks),
        }

    async def search(
        self,
        query: str,
        user_id: str = None,
        jwt_token: str = None,
        filters: Dict[str, Any] = None,
        limit: int = 10,
        score_threshold: float = 0,
        embedding_model: str = None,
    ) -> Dict[str, Any]:
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

        from auth_context import set_search_limit, set_score_threshold

        set_search_limit(limit)
        set_score_threshold(score_threshold)

        return await self.search_tool(query, embedding_model=embedding_model)