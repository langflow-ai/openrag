import copy
from typing import Any, Dict
from agentd.tool_decorator import tool
from config.settings import EMBED_MODEL, clients, INDEX_NAME, get_embedding_model
from auth_context import get_auth_context
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0


class SearchService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    @tool
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
        embedding_model = embedding_model or get_embedding_model() or EMBED_MODEL
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
                    "owners": "owner_name.keyword",
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
                    index=INDEX_NAME, body=agg_query, params={"terminate_after": 0}
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
            import asyncio

            async def embed_with_model(model_name):
                delay = EMBED_RETRY_INITIAL_DELAY
                attempts = 0
                last_exception = None

                while attempts < MAX_EMBED_RETRIES:
                    attempts += 1
                    try:
                        resp = await clients.patched_async_client.embeddings.create(
                            model=model_name, input=[query]
                        )
                        return model_name, resp.data[0].embedding
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
                    "owners": "owner_name.keyword",
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
                                "fuzziness": "AUTO",
                                "boost": 0.3,  # 30% weight for keyword search
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
                "owners": {"terms": {"field": "owner_name.keyword", "size": 10}},
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

        search_params = {"terminate_after": 0}

        try:
            results = await opensearch_client.search(
                index=INDEX_NAME, body=search_body, params=search_params
            )
        except RequestError as e:
            error_message = str(e)
            if (
                fallback_search_body is not None
                and "unknown field [num_candidates]" in error_message.lower()
            ):
                logger.warning(
                    "OpenSearch cluster does not support num_candidates; retrying without it"
                )
                try:
                    results = await opensearch_client.search(
                        index=INDEX_NAME,
                        body=fallback_search_body,
                        params=search_params,
                    )
                except RequestError as retry_error:
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
        except Exception as e:
            logger.error(
                "OpenSearch query failed", error=str(e), search_body=search_body
            )
            # Re-raise the exception so the API returns the error to frontend
            raise

        # Transform results (keep for backward compatibility)
        chunks = []
        for hit in results["hits"]["hits"]:
            chunks.append(
                {
                    "filename": hit["_source"].get("filename"),
                    "mimetype": hit["_source"].get("mimetype"),
                    "page": hit["_source"].get("page"),
                    "text": hit["_source"].get("text"),
                    "score": hit.get("_score"),
                    "source_url": hit["_source"].get("source_url"),
                    "owner": hit["_source"].get("owner"),
                    "owner_name": hit["_source"].get("owner_name"),
                    "owner_email": hit["_source"].get("owner_email"),
                    "file_size": hit["_source"].get("file_size"),
                    "connector_type": hit["_source"].get("connector_type"),
                    "embedding_model": hit["_source"].get("embedding_model"),  # Include in results
                    "embedding_dimensions": hit["_source"].get("embedding_dimensions"),
                }
            )

        # Return both transformed results and aggregations
        return {
            "results": chunks,
            "aggregations": results.get("aggregations", {}),
            "total": (
                results.get("hits", {}).get("total", {}).get("value")
                if isinstance(results.get("hits", {}).get("total"), dict)
                else results.get("hits", {}).get("total")
            ),
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
