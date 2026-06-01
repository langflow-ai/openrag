from __future__ import annotations

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from lfx.base.vectorstores.model import LCVectorStoreComponent, check_cached_vector_store
from lfx.base.vectorstores.vector_store_connection_decorator import vector_store_connection
from lfx.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    IntInput,
    MultilineInput,
    Output,
    SecretStrInput,
    StrInput,
    TableInput,
)
from lfx.log import logger
from lfx.schema.data import Data
from lfx.schema.dataframe import Table
from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import OpenSearchException, RequestError

REQUEST_TIMEOUT = 60
MAX_RETRIES = 5

# watsonx.ai surfaces rate-limit state via these (mostly non-standard) response
# headers. The IBM SDK acts on the x-requests-limit-* family directly; we log
# them on a failed embedding call to aid plan/region tuning.
_WATSONX_RATE_LIMIT_HEADERS = (
    "x-requests-limit-rate",
    "x-requests-limit-remaining",
    "x-requests-limit-reset",
    "Retry-After",
)


def _log_watsonx_rate_limit_headers(error: Exception) -> None:
    """Best-effort diagnostic: log watsonx rate-limit headers from a failed call.

    The watsonx SDK raises ``ApiRequestFailure``, which carries the originating
    httpx/requests ``Response`` as ``.response``. On a 429 exhaustion we surface
    the documented rate-limit headers so operators can tune throughput.
    """
    try:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return
        status = getattr(response, "status_code", "unknown")
        observed = {h: headers.get(h) for h in _WATSONX_RATE_LIMIT_HEADERS if headers.get(h) is not None}
        if str(status) == "429" or observed:
            logger.warning(f"watsonx rate-limit response (status={status}): {observed}")
    except Exception as log_error:  # never let diagnostics mask the real error
        logger.debug(f"Could not extract watsonx rate-limit headers: {log_error}")


def normalize_model_name(model_name: str) -> str:
    """Normalize embedding model name for use as field suffix.

    Converts model names to valid OpenSearch field names by replacing
    special characters and ensuring alphanumeric format.

    Args:
        model_name: Original embedding model name (e.g., "text-embedding-3-small")

    Returns:
        Normalized field suffix (e.g., "text_embedding_3_small")
    """
    normalized = model_name.lower()
    # Replace common separators with underscores
    normalized = normalized.replace("-", "_").replace(":", "_").replace("/", "_").replace(".", "_")
    # Remove any non-alphanumeric characters except underscores
    normalized = "".join(c if c.isalnum() or c == "_" else "_" for c in normalized)
    # Remove duplicate underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def get_embedding_field_name(model_name: str) -> str:
    """Get the dynamic embedding field name for a model.

    Args:
        model_name: Embedding model name

    Returns:
        Field name in format: chunk_embedding_{normalized_model_name}
    """
    logger.info(f"chunk_embedding_{normalize_model_name(model_name)}")
    return f"chunk_embedding_{normalize_model_name(model_name)}"


@vector_store_connection
class OpenSearchVectorStoreComponentMultimodalMultiEmbedding(LCVectorStoreComponent):
    """OpenSearch Vector Store Component with Multi-Model Hybrid Search Capabilities.

    This component provides vector storage and retrieval using OpenSearch, combining semantic
    similarity search (KNN) with keyword-based search for optimal results. It supports:
    - Multiple embedding models per index with dynamic field names
    - Automatic detection and querying of all available embedding models
    - Parallel embedding generation for multi-model search
    - Document ingestion with model tracking
    - Advanced filtering and aggregations
    - Flexible authentication options

    Features:
    - Multi-model vector storage with dynamic fields (chunk_embedding_{model_name})
    - Hybrid search combining multiple KNN queries (dis_max) + keyword matching
    - Auto-detection of available models in the index
    - Parallel query embedding generation for all detected models
    - Vector storage with configurable engines (jvector, nmslib, faiss, lucene)
    - Flexible authentication (Basic auth, JWT tokens)

    Model Name Resolution:
    - Priority: deployment > model > model_name attributes
    - This ensures correct matching between embedding objects and index fields
    - When multiple embeddings are provided, specify embedding_model_name to select which one to use
    - During search, each detected model in the index is matched to its corresponding embedding object
    """

    display_name: str = "OpenSearch (Multi-Model Multi-Embedding)"
    icon: str = "OpenSearch"
    description: str = (
        "Store and search documents using OpenSearch with multi-model hybrid semantic and keyword search. "
        "To search use the tools search_documents and raw_search. "
        "Search documents takes a query for vector search, for example\n"
        '  {search_query: "components in openrag"}'
    )

    # Keys we consider baseline
    default_keys: list[str] = [
        "opensearch_url",
        "index_name",
        *[i.name for i in LCVectorStoreComponent.inputs],  # search_query, add_documents, etc.
        "embedding",
        "embedding_model_name",
        "vector_field",
        "number_of_results",
        "auth_mode",
        "username",
        "password",
        "jwt_token",
        "jwt_header",
        "bearer_prefix",
        "use_ssl",
        "verify_certs",
        "filter_expression",
        "engine",
        "space_type",
        "ef_construction",
        "m",
        "num_candidates",
        "docs_metadata",
        "request_timeout",
        "max_retries",
        "openrag_ingest_url",
        "openrag_ingest_token",
        "openrag_ingest_run_id",
        "openrag_ingest_batch_size",
    ]
    _openrag_ingest_global_placeholders = {
        "openrag_ingest_url": "OPENRAG_INGEST_URL",
        "openrag_ingest_token": "OPENRAG_INGEST_TOKEN",
        "openrag_ingest_run_id": "OPENRAG_INGEST_RUN_ID",
    }

    inputs = [
        TableInput(
            name="docs_metadata",
            display_name="Document Metadata",
            info=(
                "Additional metadata key-value pairs to be added to all ingested documents. "
                "Useful for tagging documents with source information, categories, or other custom attributes."
            ),
            table_schema=[
                {
                    "name": "key",
                    "display_name": "Key",
                    "type": "str",
                    "description": "Key name",
                },
                {
                    "name": "value",
                    "display_name": "Value",
                    "type": "str",
                    "description": "Value of the metadata",
                },
            ],
            value=[],
            input_types=["Data", "JSON"],
        ),
        StrInput(
            name="openrag_ingest_token",
            display_name="OpenRAG Ingest Token",
            value="OPENRAG_INGEST_TOKEN",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info="Short-lived token used only for OpenRAG ingest callbacks.",
        ),
        StrInput(
            name="openrag_ingest_run_id",
            display_name="OpenRAG Ingest Run ID",
            value="OPENRAG_INGEST_RUN_ID",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
        ),
        StrInput(
            name="opensearch_url",
            display_name="OpenSearch URL",
            value="http://localhost:9200",
            info=(
                "The connection URL for your OpenSearch cluster "
                "(e.g., http://localhost:9200 for local development or your cloud endpoint)."
            ),
        ),
        StrInput(
            name="index_name",
            display_name="Index Name",
            value="langflow",
            info=(
                "The OpenSearch index name where documents will be stored and searched. "
                "Will be created automatically if it doesn't exist."
            ),
        ),
        DropdownInput(
            name="engine",
            display_name="Vector Engine",
            options=["nmslib", "faiss", "lucene", "jvector"],
            value="jvector",
            info=(
                "Vector search engine for similarity calculations. 'nmslib' works with standard "
                "OpenSearch. 'jvector' requires OpenSearch 2.9+. 'lucene' requires index.knn: true. "
                "Amazon OpenSearch Serverless only supports 'nmslib' or 'faiss'."
            ),
            advanced=True,
        ),
        DropdownInput(
            name="space_type",
            display_name="Distance Metric",
            options=["l2", "l1", "cosinesimil", "linf", "innerproduct"],
            value="l2",
            info=(
                "Distance metric for calculating vector similarity. 'l2' (Euclidean) is most common, "
                "'cosinesimil' for cosine similarity, 'innerproduct' for dot product."
            ),
            advanced=True,
        ),
        IntInput(
            name="ef_construction",
            display_name="EF Construction",
            value=512,
            info=(
                "Size of the dynamic candidate list during index construction. "
                "Higher values improve recall but increase indexing time and memory usage."
            ),
            advanced=True,
        ),
        IntInput(
            name="m",
            display_name="M Parameter",
            value=16,
            info=(
                "Number of bidirectional connections for each vector in the HNSW graph. "
                "Higher values improve search quality but increase memory usage and indexing time."
            ),
            advanced=True,
        ),
        IntInput(
            name="num_candidates",
            display_name="Candidate Pool Size",
            value=1000,
            info=(
                "Number of approximate neighbors to consider for each KNN query. "
                "Some OpenSearch deployments do not support this parameter; set to 0 to disable."
            ),
            advanced=True,
        ),
        *LCVectorStoreComponent.inputs,  # includes search_query, add_documents, etc.
        HandleInput(
            name="embedding", display_name="Embedding", input_types=["Embeddings"], is_list=True
        ),
        StrInput(
            name="embedding_model_name",
            display_name="Embedding Model Name",
            value="",
            info=(
                "Name of the embedding model to use for ingestion. This selects which embedding from the list "
                "will be used to embed documents. Matches on deployment, model, model_id, or model_name. "
                "For duplicate deployments, use combined format: 'deployment:model' "
                "(e.g., 'text-embedding-ada-002:text-embedding-3-large'). "
                "Leave empty to use the first embedding. Error message will show all available identifiers."
            ),
            advanced=False,
        ),
        StrInput(
            name="vector_field",
            display_name="Legacy Vector Field Name",
            value="chunk_embedding",
            advanced=True,
            info=(
                "Legacy field name for backward compatibility. New documents use dynamic fields "
                "(chunk_embedding_{model_name}) based on the embedding_model_name."
            ),
        ),
        IntInput(
            name="number_of_results",
            display_name="Default Result Limit",
            value=10,
            advanced=True,
            info=(
                "Default maximum number of search results to return when no limit is "
                "specified in the filter expression."
            ),
        ),
        MultilineInput(
            name="filter_expression",
            display_name="Search Filters (JSON)",
            value="",
            info=(
                "Optional JSON configuration for search filtering, result limits, and score thresholds.\n\n"
                "Format 1 - Explicit filters:\n"
                '{"filter": [{"term": {"filename":"doc.pdf"}}, '
                '{"terms":{"owner":["user1","user2"]}}], "limit": 10, "score_threshold": 1.6}\n\n'
                "Format 2 - Context-style mapping:\n"
                '{"data_sources":["file.pdf"], "document_types":["application/pdf"], "owners":["user123"]}\n\n'
                "Use __IMPOSSIBLE_VALUE__ as placeholder to ignore specific filters."
            ),
        ),
        # ----- Auth controls (dynamic) -----
        DropdownInput(
            name="auth_mode",
            display_name="Authentication Mode",
            value="openrag",
            options=["basic", "jwt", "openrag"],
            info=(
                "Authentication method: 'basic' for username/password authentication, "
                "'jwt' for JSON Web Token (Bearer) authentication, or 'openrag' to "
                "delegate writes to the OpenRAG backend ingest callback (no direct "
                "OpenSearch credentials required — only OPENRAG_* fields)."
            ),
            real_time_refresh=True,
            advanced=False,
        ),
        StrInput(
            name="username",
            display_name="Username",
            value="admin",
            show=True,
        ),
        SecretStrInput(
            name="password",
            display_name="OpenSearch Password",
            value="admin",
            show=True,
        ),
        SecretStrInput(
            name="jwt_token",
            display_name="JWT Token",
            value="JWT",
            load_from_db=False,
            show=False,
            info=(
                "Valid JSON Web Token for authentication. "
                "Will be sent in the Authorization header (with optional 'Bearer ' prefix)."
            ),
            required=False
        ),
        StrInput(
            name="jwt_header",
            display_name="JWT Header Name",
            value="Authorization",
            show=False,
            advanced=True,
        ),
        BoolInput(
            name="bearer_prefix",
            display_name="Prefix 'Bearer '",
            value=False,
            show=False,
            advanced=True,
        ),
        # ----- TLS -----
        BoolInput(
            name="use_ssl",
            display_name="Use SSL/TLS",
            value=True,
            advanced=True,
            info="Enable SSL/TLS encryption for secure connections to OpenSearch.",
        ),
        BoolInput(
            name="verify_certs",
            display_name="Verify SSL Certificates",
            value=False,
            advanced=True,
            info=(
                "Verify SSL certificates when connecting. "
                "Disable for self-signed certificates in development environments."
            ),
        ),
        # ----- Timeout / Retry -----
        StrInput(
            name="request_timeout",
            display_name="Request Timeout (seconds)",
            value="60",
            advanced=True,
            info=(
                "Time in seconds to wait for a response from OpenSearch. "
                "Increase for large bulk ingestion or complex hybrid queries."
            ),
        ),
        StrInput(
            name="max_retries",
            display_name="Max Retries",
            value="3",
            advanced=True,
            info="Number of retries for failed connections before raising an error.",
        ),
        StrInput(
            name="openrag_ingest_url",
            display_name="OpenRAG Ingest URL",
            value="OPENRAG_INGEST_URL",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info="Internal OpenRAG callback URL for backend-owned document indexing.",
        ),
        StrInput(
            name="openrag_ingest_token",
            display_name="OpenRAG Ingest Token",
            value="OPENRAG_INGEST_TOKEN",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info="Short-lived token used only for OpenRAG ingest callbacks.",
        ),
        StrInput(
            name="openrag_ingest_run_id",
            display_name="OpenRAG Ingest Run ID",
            value="OPENRAG_INGEST_RUN_ID",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
        ),
        IntInput(
            name="openrag_ingest_batch_size",
            display_name="OpenRAG Ingest Batch Size",
            value=100,
            advanced=True,
        ),
    ]
    outputs = [
        Output(
            display_name="Search Results",
            name="search_results",
            method="search_documents",
        ),
        Output(display_name="Raw Search", name="raw_search", method="raw_search"),
    ]

    def raw_search(self, query: str | dict | None = None) -> Data:
        """Execute a raw OpenSearch query against the target index.

        Args:
            query (dict[str, Any]): The OpenSearch query DSL dictionary.

        Returns:
            Data: Search results as a Data object.

        Raises:
            ValueError: If 'query' is not a valid OpenSearch query (must be a non-empty dict).
        """
        raw_query = query if query is not None else self.search_query

        if raw_query is None or (isinstance(raw_query, str) and not raw_query.strip()):
            self.log("No query provided for raw search - returning empty results")
            return Data(data={})

        if isinstance(raw_query, dict):
            query_body = copy.deepcopy(raw_query)
        elif isinstance(raw_query, str):
            s = raw_query.strip()

            # First, optimistically try to parse as JSON DSL
            try:
                query_body = json.loads(s)
            except json.JSONDecodeError:
                # Fallback: treat as a basic text query over common fields
                query_body = {
                    "query": {
                        "multi_match": {
                            "query": s,
                            "fields": ["text^2", "filename^1.5"],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                        }
                    }
                }
        else:
            msg = f"Unsupported raw_search query type: {type(raw_query)!r}"
            raise TypeError(msg)

        filter_obj = self._parse_filter_expression()
        filter_clauses = self._coerce_filter_clauses(filter_obj)

        if filter_clauses:
            if "query" in query_body:
                original_query = query_body["query"]
                query_body["query"] = {
                    "bool": {
                        "must": [original_query],
                        "filter": filter_clauses,
                    }
                }
            else:
                query_body["query"] = {
                    "bool": {
                        "must": [{"match_all": {}}],
                        "filter": filter_clauses,
                    }
                }

        if filter_obj:
            # Apply limit if not already set in the raw query
            if "size" not in query_body:
                limit = self._resolve_limit(filter_obj, default_limit=None)
                if limit is not None:
                    query_body["size"] = limit

            # Apply score_threshold / scoreThreshold as min_score if not already set
            if "min_score" not in query_body:

                score_threshold = self._resolve_score_threshold(filter_obj)
                if score_threshold is not None:

                    query_body["min_score"] = score_threshold

        client = self.build_client()
        logger.info(f"query: {query_body}")
        resp = client.search(
            index=self.index_name,
            body=query_body,
            params={"terminate_after": 0},
        )
        # Remove any _source keys whose value is a list of floats (embedding vectors)
        # Minimum length threshold to identify embedding vectors
        min_vector_length = 100

        def is_vector(val):
            # Accepts if it's a list of numbers (float or int) and has reasonable vector length
            return (
                isinstance(val, list)
                and len(val) > min_vector_length
                and all(isinstance(x, (float, int)) for x in val)
            )

        if "hits" in resp and "hits" in resp["hits"]:
            for hit in resp["hits"]["hits"]:
                source = hit.get("_source")
                if isinstance(source, dict):
                    keys_to_remove = [k for k, v in source.items() if is_vector(v)]
                    for k in keys_to_remove:
                        source.pop(k)
        logger.info(f"Raw search response (all embedding vectors removed): {resp}")
        return Data(**resp)

    def _get_embedding_model_name(self, embedding_obj=None) -> str:
        """Get the embedding model name from component config or embedding object.

        Priority: deployment > model > model_id > model_name
        This ensures we use the actual model being deployed, not just the configured model.
        Supports multiple embedding providers (OpenAI, Watsonx, Cohere, etc.)

        Args:
            embedding_obj: Specific embedding object to get name from (optional)

        Returns:
            Embedding model name

        Raises:
            ValueError: If embedding model name cannot be determined
        """
        # First try explicit embedding_model_name input
        if hasattr(self, "embedding_model_name") and self.embedding_model_name:
            return self.embedding_model_name.strip()

        # Try to get from provided embedding object
        if embedding_obj:
            # Priority: deployment > model > model_id > model_name
            if hasattr(embedding_obj, "deployment") and embedding_obj.deployment:
                return str(embedding_obj.deployment)
            if hasattr(embedding_obj, "model") and embedding_obj.model:
                return str(embedding_obj.model)
            if hasattr(embedding_obj, "model_id") and embedding_obj.model_id:
                return str(embedding_obj.model_id)
            if hasattr(embedding_obj, "model_name") and embedding_obj.model_name:
                return str(embedding_obj.model_name)

        # Try to get from embedding component (legacy single embedding)
        if hasattr(self, "embedding") and self.embedding:
            # Handle list of embeddings
            if isinstance(self.embedding, list) and len(self.embedding) > 0:
                first_emb = self.embedding[0]
                if hasattr(first_emb, "deployment") and first_emb.deployment:
                    return str(first_emb.deployment)
                if hasattr(first_emb, "model") and first_emb.model:
                    return str(first_emb.model)
                if hasattr(first_emb, "model_id") and first_emb.model_id:
                    return str(first_emb.model_id)
                if hasattr(first_emb, "model_name") and first_emb.model_name:
                    return str(first_emb.model_name)
            # Handle single embedding
            elif not isinstance(self.embedding, list):
                if hasattr(self.embedding, "deployment") and self.embedding.deployment:
                    return str(self.embedding.deployment)
                if hasattr(self.embedding, "model") and self.embedding.model:
                    return str(self.embedding.model)
                if hasattr(self.embedding, "model_id") and self.embedding.model_id:
                    return str(self.embedding.model_id)
                if hasattr(self.embedding, "model_name") and self.embedding.model_name:
                    return str(self.embedding.model_name)

        msg = (
            "Could not determine embedding model name. "
            "Please set the 'embedding_model_name' field or ensure the embedding component "
            "has a 'deployment', 'model', 'model_id', or 'model_name' attribute."
        )
        raise ValueError(msg)

    # ---------- helper functions for index management ----------
    def _default_text_mapping(
        self,
        dim: int,
        engine: str = "jvector",
        space_type: str = "l2",
        ef_search: int = 512,
        ef_construction: int = 100,
        m: int = 16,
        vector_field: str = "vector_field",
    ) -> dict[str, Any]:
        """Create the default OpenSearch index mapping for vector search.

        This method generates the index configuration with k-NN settings optimized
        for approximate nearest neighbor search using the specified vector engine.
        Includes the embedding_model keyword field for tracking which model was used.

        Args:
            dim: Dimensionality of the vector embeddings
            engine: Vector search engine (jvector, nmslib, faiss, lucene)
            space_type: Distance metric for similarity calculation
            ef_search: Size of dynamic list used during search
            ef_construction: Size of dynamic list used during index construction
            m: Number of bidirectional links for each vector
            vector_field: Name of the field storing vector embeddings

        Returns:
            Dictionary containing OpenSearch index mapping configuration
        """
        return {
            "settings": {"index": {"knn": True, "knn.algo_param.ef_search": ef_search}},
            "mappings": {
                "properties": {
                    vector_field: {
                        "type": "knn_vector",
                        "dimension": dim,
                        "method": {
                            "name": "disk_ann",
                            "space_type": space_type,
                            "engine": engine,
                            "parameters": {"ef_construction": ef_construction, "m": m},
                        },
                    },
                    "embedding_model": {"type": "keyword"},  # Track which model was used
                    "embedding_dimensions": {"type": "integer"},
                }
            },
        }

    def _ensure_embedding_field_mapping(
        self,
        client: OpenSearch,
        index_name: str,
        field_name: str,
        dim: int,
        engine: str,
        space_type: str,
        ef_construction: int,
        m: int,
    ) -> None:
        """Lazily add a dynamic embedding field to the index if it doesn't exist.

        This allows adding new embedding models without recreating the entire index.
        Also ensures the embedding_model tracking field exists.

        Note: Some OpenSearch versions/configurations have issues with dynamically adding
        knn_vector mappings (NullPointerException). This method checks if the field
        already exists before attempting to add it, and gracefully skips if the field
        is already properly configured.

        Args:
            client: OpenSearch client instance
            index_name: Target index name
            field_name: Dynamic field name for this embedding model
            dim: Vector dimensionality
            engine: Vector search engine
            space_type: Distance metric
            ef_construction: Construction parameter
            m: HNSW parameter
        """
        # First, check if the field already exists and is properly mapped
        properties = self._get_index_properties(client)
        if self._is_knn_vector_field(properties, field_name):
            # Field already exists as knn_vector - verify dimensions match
            existing_dim = self._get_field_dimension(properties, field_name)
            if existing_dim is not None and existing_dim != dim:
                logger.warning(
                    f"Field '{field_name}' exists with dimension {existing_dim}, "
                    f"but current embedding has dimension {dim}. Using existing mapping."
                )
            else:
                logger.info(
                    f"[OpenSearchMultimodel] Field '{field_name}' already exists"
                    f"as knn_vector with matching dimensions - skipping mapping update"
                )
            return

        # Field doesn't exist, try to add the mapping
        try:
            mapping = {
                "properties": {
                    field_name: {
                        "type": "knn_vector",
                        "dimension": dim,
                        "method": {
                            "name": "disk_ann",
                            "space_type": space_type,
                            "engine": engine,
                            "parameters": {"ef_construction": ef_construction, "m": m},
                        },
                    },
                    # Also ensure the embedding_model tracking field exists as keyword
                    "embedding_model": {"type": "keyword"},
                    "embedding_dimensions": {"type": "integer"},
                }
            }
            client.indices.put_mapping(index=index_name, body=mapping)
            logger.info(f"Added/updated embedding field mapping: {field_name}")
        except RequestError as e:
            error_str = str(e).lower()
            if "invalid engine" in error_str and "jvector" in error_str:
                msg = (
                    "The 'jvector' engine is not available in your OpenSearch installation. "
                    "Use 'nmslib' or 'faiss' for standard OpenSearch, or upgrade to OpenSearch 2.9+."
                )
                raise ValueError(msg) from e
            if "index.knn" in error_str:
                msg = (
                    "The index has index.knn: false. Delete the existing index and let the "
                    "component recreate it, or create a new index with a different name."
                )
                raise ValueError(msg) from e
            raise
        except Exception as e:
            # Check if this is the known OpenSearch k-NN NullPointerException issue
            error_str = str(e).lower()
            if "null" in error_str or "nullpointerexception" in error_str:
                logger.warning(
                    f"[OpenSearchMultimodel] Could not add embedding field mapping for {field_name}"
                    f"due to OpenSearch k-NN plugin issue: {e}. "
                    f"This is a known issue with some OpenSearch versions. "
                    f"[OpenSearchMultimodel] Skipping mapping update. "
                    f"Please ensure the index has the correct mapping for KNN search to work."
                )
                # Skip and continue - ingestion will proceed, but KNN search may fail if mapping doesn't exist
                return
            logger.warning(
                f"[OpenSearchMultimodel] Could not add embedding field mapping for {field_name}: {e}"
            )
            raise

        # Verify the field was added correctly
        properties = self._get_index_properties(client)
        if not self._is_knn_vector_field(properties, field_name):
            msg = f"Field '{field_name}' is not mapped as knn_vector. Current mapping: {properties.get(field_name)}"
            logger.error(msg)
            raise ValueError(msg)

    def _validate_aoss_with_engines(self, *, is_aoss: bool, engine: str) -> None:
        """Validate engine compatibility with Amazon OpenSearch Serverless (AOSS).

        Amazon OpenSearch Serverless has restrictions on which vector engines
        can be used. This method ensures the selected engine is compatible.

        Args:
            is_aoss: Whether the connection is to Amazon OpenSearch Serverless
            engine: The selected vector search engine

        Raises:
            ValueError: If AOSS is used with an incompatible engine
        """
        if is_aoss and engine not in {"nmslib", "faiss"}:
            msg = "Amazon OpenSearch Service Serverless only supports `nmslib` or `faiss` engines"
            raise ValueError(msg)

    def _is_aoss_enabled(self, http_auth: Any) -> bool:
        """Determine if Amazon OpenSearch Serverless (AOSS) is being used.

        Args:
            http_auth: The HTTP authentication object

        Returns:
            True if AOSS is enabled, False otherwise
        """
        return (
            http_auth is not None and hasattr(http_auth, "service") and http_auth.service == "aoss"
        )

    @staticmethod
    def _openrag_input_to_str(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if hasattr(value, "text"):
            value = value.text
        return str(value or "").strip()

    def _openrag_callback_value(self, attr_name: str) -> str:
        value = self._openrag_input_to_str(getattr(self, attr_name, ""))
        if value == self._openrag_ingest_global_placeholders.get(attr_name):
            return ""
        return value

    def _openrag_ingest_callback_config(self) -> tuple[str, str, str] | None:
        url = self._openrag_callback_value("openrag_ingest_url")
        token = self._openrag_callback_value("openrag_ingest_token")
        ingest_run_id = self._openrag_callback_value("openrag_ingest_run_id")

        masked_token = (
            f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else ("<set>" if token else "")
        )
        debug_payload = {
            "openrag_ingest_url": url,
            "openrag_ingest_url_len": len(url),
            "openrag_ingest_token_masked": masked_token,
            "openrag_ingest_token_len": len(token),
            "openrag_ingest_run_id": ingest_run_id,
            "raw_url_type": type(self.openrag_ingest_url).__name__,
            "raw_token_type": type(self.openrag_ingest_token).__name__,
            "raw_run_id_type": type(self.openrag_ingest_run_id).__name__,
        }
        logger.warning(f"[OpenRAG callback config] {debug_payload}")
        try:
            self.log(f"[OpenRAG callback config] {debug_payload}")
        except Exception:
            pass

        if not url and not token and not ingest_run_id:
            return None
        if not url or not token or not ingest_run_id:
            msg = "OpenRAG ingest callback requires url, token, and ingest_run_id."
            raise ValueError(msg)
        return url, token, ingest_run_id

    def _post_openrag_ingest_batches(
        self,
        *,
        requests: list[dict],
        vector_field: str,
        text_field: str,
    ) -> None:
        callback_config = self._openrag_ingest_callback_config()
        if callback_config is None:
            return

        url, token, ingest_run_id = callback_config
        batch_size = max(self._parse_int_param("openrag_ingest_batch_size", 100), 1)
        timeout = self._parse_int_param("request_timeout", REQUEST_TIMEOUT)
        headers = {"Authorization": f"Bearer {token}"}

        masked_token = (
            f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else ("<set>" if token else "")
        )
        request_summary = {
            "url": url,
            "ingest_run_id": ingest_run_id,
            "token_masked": masked_token,
            "total_chunks": len(requests),
            "batch_size": batch_size,
            "timeout_s": timeout,
        }
        logger.warning(f"[OpenRAG ingest POST] {request_summary}")
        try:
            self.log(f"[OpenRAG ingest POST] {request_summary}")
        except Exception:
            pass

        with httpx.Client(timeout=timeout) as client:
            total_batches = (len(requests) + batch_size - 1) // batch_size
            for batch_number, start in enumerate(range(0, len(requests), batch_size), start=1):
                batch = requests[start : start + batch_size]
                final = batch_number == total_batches
                payload = {
                    "ingest_run_id": ingest_run_id,
                    "batch_id": batch_number,
                    "final": final,
                    "chunks": [
                        self._openrag_chunk_payload(
                            request,
                            vector_field=vector_field,
                            text_field=text_field,
                        )
                        for request in batch
                    ],
                }
                logger.warning(
                    f"[OpenRAG ingest POST] -> batch={batch_number}/{total_batches} "
                    f"url={url} chunks={len(payload['chunks'])} final={final}"
                )
                response = client.post(url, json=payload, headers=headers)
                response_summary = {
                    "batch": batch_number,
                    "url": url,
                    "status": response.status_code,
                    "final_url": str(response.request.url),
                    "response_headers": dict(response.headers),
                    "body_preview": response.text[:500],
                }
                logger.warning(f"[OpenRAG ingest POST resp] {response_summary}")
                try:
                    self.log(f"[OpenRAG ingest POST resp] {response_summary}")
                except Exception:
                    pass
                if response.status_code >= 400:
                    msg = (
                        "OpenRAG ingest callback failed "
                        f"(batch={batch_number}, status={response.status_code}, "
                        f"url={url}): {response.text[:1000]}"
                    )
                    raise RuntimeError(msg)

        self.log(f"Posted {len(requests)} chunks to OpenRAG backend ingest callback.")

    @staticmethod
    def _openrag_chunk_payload(
        request: dict,
        *,
        vector_field: str,
        text_field: str,
    ) -> dict:
        metadata = {
            key: value
            for key, value in request.items()
            if key not in {"_op_type", "_index", "_id", "id", vector_field, text_field}
        }
        page = metadata.get("page")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        return {
            "id": request.get("_id") or request.get("id"),
            "text": request.get(text_field, ""),
            "vector": request[vector_field],
            "page": page if isinstance(page, int) else None,
            "metadata": metadata,
        }

    def _bulk_ingest_embeddings(
        self,
        client: OpenSearch,
        index_name: str,
        embeddings: list[list[float]],
        texts: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
        vector_field: str = "vector_field",
        text_field: str = "text",
        embedding_model: str = "unknown",
        mapping: dict | None = None,
        max_chunk_bytes: int | None = 1 * 1024 * 1024,
        *,
        is_aoss: bool = False,
    ) -> list[str]:
        """Efficiently ingest multiple documents with embeddings into OpenSearch.

        This method uses bulk operations to insert documents with their vector
        embeddings and metadata into the specified OpenSearch index. Each document
        is tagged with the embedding_model name for tracking.

        Args:
            client: OpenSearch client instance
            index_name: Target index for document storage
            embeddings: List of vector embeddings for each document
            texts: List of document texts
            metadatas: Optional metadata dictionaries for each document
            ids: Optional document IDs (UUIDs generated if not provided)
            vector_field: Field name for storing vector embeddings
            text_field: Field name for storing document text
            embedding_model: Name of the embedding model used
            mapping: Optional index mapping configuration
            max_chunk_bytes: Maximum size per bulk request chunk
            is_aoss: Whether using Amazon OpenSearch Serverless

        Returns:
            List of document IDs that were successfully ingested
        """
        logger.debug(f"[OpenSearchMultimodel] Bulk ingesting embeddings for {index_name}")
        if not mapping:
            mapping = {}

        requests = []
        return_ids = []
        vector_dimensions = len(embeddings[0]) if embeddings else None

        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas else {}
            if vector_dimensions is not None and "embedding_dimensions" not in metadata:
                metadata = {**metadata, "embedding_dimensions": vector_dimensions}

            # Normalize ACL fields that may arrive as JSON strings from flows
            for key in ("allowed_users", "allowed_groups", "allowed_principals"):
                value = metadata.get(key)
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            metadata[key] = parsed
                    except (json.JSONDecodeError, TypeError):
                        # Leave value as-is if it isn't valid JSON
                        pass

            metadata_document_id = str(metadata.get("document_id") or "").strip()
            if metadata_document_id and metadata_document_id.lower() != "none":
                generated_id = f"{metadata_document_id}_{i}"
            else:
                generated_id = str(uuid.uuid4())
            _id = ids[i] if ids else generated_id
            request = {
                "_op_type": "index",
                "_index": index_name,
                vector_field: embeddings[i],
                text_field: text,
                "embedding_model": embedding_model,  # Track which model was used
                **metadata,
            }
            if is_aoss:
                request["id"] = _id
            else:
                request["_id"] = _id
            requests.append(request)
            return_ids.append(_id)
        if metadatas:
            self.log(f"Sample metadata: {metadatas[0] if metadatas else {}}")
        if self._openrag_ingest_callback_config() is not None:
            self._post_openrag_ingest_batches(
                requests=requests,
                vector_field=vector_field,
                text_field=text_field,
            )
            return return_ids
        try:
            helpers.bulk(client, requests, max_chunk_bytes=max_chunk_bytes)
        except Exception as bulk_error:
            if "Unsupported request type for filter level DLS" not in str(bulk_error):
                raise
            logger.warning(
                "[OpenSearchMultimodel] Bulk ingest is blocked by filter-level DLS; "
                "falling back to per-document index requests."
            )
            self._index_embeddings_individually(client, requests)
        return return_ids

    def _index_embeddings_individually(
        self,
        client: OpenSearch,
        requests: list[dict],
    ) -> None:
        """Index documents one at a time when OpenSearch DLS rejects bulk writes."""
        for request in requests:
            document_id = request.get("_id") or request.get("id")
            body = {
                key: value
                for key, value in request.items()
                if key not in {"_op_type", "_index", "_id", "id"}
            }
            client.index(index=request["_index"], id=document_id, body=body)

    def _log_index_admin_skip(self, operation: str, error: Exception) -> None:
        """Log index-admin operations that may be blocked under filter-level DLS."""
        logger.warning(
            f"[OpenSearchMultimodel] Could not run index-admin operation '{operation}': {error}. "
            "Assuming the backend pre-created the required index/mapping and continuing."
        )

    # ---------- param helpers ----------
    def _parse_int_param(self, attr_name: str, default: int) -> int:
        """Parse a string attribute to int, returning *default* on failure."""
        raw = getattr(self, attr_name, None)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            value = int(str(raw).strip())
        except ValueError:
            logger.warning(
                f"Invalid integer value '{raw}' for {attr_name}, using default {default}"
            )
            return default

        if value < 0:
            logger.warning(f"Negative value '{raw}' for {attr_name}, using default {default}")
            return default

        return value

    # ---------- auth / client ----------
    def _build_auth_kwargs(self) -> dict[str, Any]:
        """Build authentication configuration for OpenSearch client.

        Constructs the appropriate authentication parameters based on the
        selected auth mode (basic username/password or JWT token).

        Returns:
            Dictionary containing authentication configuration

        Raises:
            ValueError: If required authentication parameters are missing
        """
        mode = (self.auth_mode or "basic").strip().lower()
        if mode == "jwt":
            token = (self.jwt_token or "").strip()
            if not token:
                msg = "Auth Mode is 'jwt' but no jwt_token was provided."
                raise ValueError(msg)
            header_name = (self.jwt_header or "Authorization").strip()
            header_value = f"Bearer {token}" if self.bearer_prefix else token
            return {"headers": {header_name: header_value}}
        if mode == "openrag":
            # Writes are delegated to the OpenRAG backend ingest callback,
            # so no direct OpenSearch credentials are needed. Only the
            # OPENRAG_* fields are required for ingestion to function.
            missing = [
                name
                for name, value in (
                    ("openrag_ingest_url", self.openrag_ingest_url),
                    ("openrag_ingest_token", self.openrag_ingest_token),
                    ("openrag_ingest_run_id", self.openrag_ingest_run_id),
                )
                if not (value or "").strip()
            ]
            if missing:
                msg = (
                    "Auth Mode is 'openrag' but required OPENRAG_* fields are "
                    f"missing: {', '.join(missing)}."
                )
                raise ValueError(msg)
            return {}
        user = (self.username or "").strip()
        pwd = (self.password or "").strip()
        if not user or not pwd:
            msg = "Auth Mode is 'basic' but username/password are missing."
            raise ValueError(msg)
        return {"http_auth": (user, pwd)}

    def build_client(self) -> OpenSearch:
        """Create and configure an OpenSearch client instance.

        Returns:
            Configured OpenSearch client ready for operations
        """
        logger.debug("[OpenSearchMultimodel] Building OpenSearch client")
        auth_kwargs = self._build_auth_kwargs()
        return OpenSearch(
            hosts=[self.opensearch_url],
            use_ssl=self.use_ssl,
            verify_certs=self.verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            timeout=self._parse_int_param("request_timeout", REQUEST_TIMEOUT),
            max_retries=self._parse_int_param("max_retries", MAX_RETRIES),
            retry_on_timeout=True,
            **auth_kwargs,
        )

    @check_cached_vector_store
    def build_vector_store(self) -> OpenSearch:
        # Return raw OpenSearch client as our "vector store."
        client = self.build_client()

        # Check if we're in ingestion-only mode (no search query)
        has_search_query = bool((self.search_query or "").strip())
        if not has_search_query:
            logger.debug(
                "[OpenSearchMultimodel] Ingestion-only mode activated: search operations will be skipped"
            )
            logger.debug("[OpenSearchMultimodel] Starting ingestion mode...")

        logger.debug(f"[OpenSearchMultimodel] Embedding: {self.embedding}")
        self._add_documents_to_vector_store(client=client)
        return client

    # ---------- ingest ----------
    def _add_documents_to_vector_store(self, client: OpenSearch) -> None:
        """Process and ingest documents into the OpenSearch vector store.

        This method handles the complete document ingestion pipeline:
        - Prepares document data and metadata
        - Generates vector embeddings using the selected model
        - Creates appropriate index mappings with dynamic field names
        - Bulk inserts documents with vectors and model tracking

        Args:
            client: OpenSearch client for performing operations
        """
        logger.debug("[OpenSearchMultimodel][INGESTION] _add_documents_to_vector_store called")
        # Convert DataFrame to Data if needed using parent's method
        self.ingest_data = self._prepare_ingest_data()

        logger.debug(
            f"[OpenSearchMultimodel][INGESTION] ingest_data type: "
            f"{type(self.ingest_data)}, length: {len(self.ingest_data) if self.ingest_data else 0}"
        )
        logger.debug(
            f"[OpenSearchMultimodel][INGESTION] ingest_data content: "
            f"{self.ingest_data[:2] if self.ingest_data and len(self.ingest_data) > 0 else 'empty'}"
        )

        docs = self.ingest_data or []
        if not docs:
            logger.debug("Ingestion complete: No documents provided")
            return

        if not self.embedding:
            msg = "Embedding handle is required to embed documents."
            raise ValueError(msg)

        # Normalize embedding to list first
        embeddings_list = self.embedding if isinstance(self.embedding, list) else [self.embedding]

        # Filter out None values (fail-safe mode) - do this BEFORE checking if empty
        embeddings_list = [e for e in embeddings_list if e is not None]

        # NOW check if we have any valid embeddings left after filtering
        if not embeddings_list:
            logger.warning(
                "All embeddings returned None (fail-safe mode enabled). Skipping document ingestion."
            )
            self.log(
                "Embedding returned None (fail-safe mode enabled). Skipping document ingestion."
            )
            return

        logger.debug(
            f"[OpenSearchMultimodel][INGESTION] Valid embeddings after filtering: {len(embeddings_list)}"
        )
        self.log(
            f"[OpenSearchMultimodel][INGESTION] Available embedding models: {len(embeddings_list)}"
        )

        # Select the embedding to use for ingestion
        selected_embedding = None
        embedding_model = None

        # If embedding_model_name is specified, find matching embedding
        if (
            hasattr(self, "embedding_model_name")
            and self.embedding_model_name
            and self.embedding_model_name.strip()
        ):
            target_model_name = self.embedding_model_name.strip()
            self.log(f"Looking for embedding model: {target_model_name}")

            for emb_obj in embeddings_list:
                # Check all possible model identifiers (deployment, model, model_id, model_name)
                # Also check available_models list from EmbeddingsWithModels
                possible_names = []
                deployment = getattr(emb_obj, "deployment", None)
                model = getattr(emb_obj, "model", None)
                model_id = getattr(emb_obj, "model_id", None)
                model_name = getattr(emb_obj, "model_name", None)
                available_models_attr = getattr(emb_obj, "available_models", None)

                if deployment:
                    possible_names.append(str(deployment))
                if model:
                    possible_names.append(str(model))
                if model_id:
                    possible_names.append(str(model_id))
                if model_name:
                    possible_names.append(str(model_name))

                # Also add combined identifier
                if deployment and model and deployment != model:
                    possible_names.append(f"{deployment}:{model}")

                # Add all models from available_models dict
                if available_models_attr and isinstance(available_models_attr, dict):
                    possible_names.extend(
                        str(model_key).strip()
                        for model_key in available_models_attr
                        if model_key and str(model_key).strip()
                    )

                # Match if target matches any of the possible names
                if target_model_name in possible_names:
                    # Check if target is in available_models dict - use dedicated instance
                    if (
                        available_models_attr
                        and isinstance(available_models_attr, dict)
                        and target_model_name in available_models_attr
                    ):
                        # Use the dedicated embedding instance from the dict
                        selected_embedding = available_models_attr[target_model_name]
                        embedding_model = target_model_name
                        self.log(
                            f"Found dedicated embedding instance for '{embedding_model}' in available_models dict"
                        )
                    else:
                        # Traditional identifier match
                        selected_embedding = emb_obj
                        embedding_model = self._get_embedding_model_name(emb_obj)
                        self.log(
                            f"Found matching embedding model: {embedding_model} (matched on: {target_model_name})"
                        )
                    break

            if not selected_embedding:
                # Build detailed list of available embeddings with all their identifiers
                available_info = []
                for idx, emb in enumerate(embeddings_list):
                    emb_type = type(emb).__name__
                    identifiers = []
                    deployment = getattr(emb, "deployment", None)
                    model = getattr(emb, "model", None)
                    model_id = getattr(emb, "model_id", None)
                    model_name = getattr(emb, "model_name", None)
                    available_models_attr = getattr(emb, "available_models", None)

                    if deployment:
                        identifiers.append(f"deployment='{deployment}'")
                    if model:
                        identifiers.append(f"model='{model}'")
                    if model_id:
                        identifiers.append(f"model_id='{model_id}'")
                    if model_name:
                        identifiers.append(f"model_name='{model_name}'")

                    # Add combined identifier as an option
                    if deployment and model and deployment != model:
                        identifiers.append(f"combined='{deployment}:{model}'")

                    # Add available_models dict if present
                    if available_models_attr and isinstance(available_models_attr, dict):
                        identifiers.append(f"available_models={list(available_models_attr.keys())}")

                    available_info.append(
                        f"  [{idx}] {emb_type}: {', '.join(identifiers) if identifiers else 'No identifiers'}"
                    )

                msg = (
                    f"Embedding model '{target_model_name}' not found in available embeddings.\n\n"
                    f"Available embeddings:\n" + "\n".join(available_info) + "\n\n"
                    "Please set 'embedding_model_name' to one of the identifier values shown above "
                    "(use the value after the '=' sign, without quotes).\n"
                    "For duplicate deployments, use the 'combined' format.\n"
                    "Or leave it empty to use the first embedding."
                )
                raise ValueError(msg)
        else:
            # Use first embedding if no model name specified
            selected_embedding = embeddings_list[0]
            embedding_model = self._get_embedding_model_name(selected_embedding)
            self.log(f"No embedding_model_name specified, using first embedding: {embedding_model}")

        dynamic_field_name = get_embedding_field_name(embedding_model)

        logger.info(f"Selected embedding model for ingestion: '{embedding_model}'")
        self.log(f"Using embedding model for ingestion: {embedding_model}")
        self.log(f"Dynamic vector field: {dynamic_field_name}")

        # Log embedding details for debugging
        if hasattr(selected_embedding, "deployment"):
            logger.info(f"Embedding deployment: {selected_embedding.deployment}")
        if hasattr(selected_embedding, "model"):
            logger.info(f"Embedding model: {selected_embedding.model}")
        if hasattr(selected_embedding, "model_id"):
            logger.info(f"Embedding model_id: {selected_embedding.model_id}")
        if hasattr(selected_embedding, "dimensions"):
            logger.info(f"Embedding dimensions: {selected_embedding.dimensions}")
        if hasattr(selected_embedding, "available_models"):
            logger.info(f"Embedding available_models: {selected_embedding.available_models}")

        # No model switching needed - each model in available_models has its own dedicated instance
        # The selected_embedding is already configured correctly for the target model
        logger.info(
            f"Using embedding instance for '{embedding_model}' - pre-configured and ready to use"
        )

        # Extract texts and metadata from documents
        texts = []
        metadatas = []
        # Process docs_metadata table input into a dict
        additional_metadata = {}
        logger.debug(f"[LF] Docs metadata {self.docs_metadata}")
        if hasattr(self, "docs_metadata") and self.docs_metadata:
            logger.info(f"[LF] Docs metadata {self.docs_metadata}")
            if isinstance(self.docs_metadata[-1], Data):
                logger.info(f"[LF] Docs metadata is a Data object {self.docs_metadata}")
                self.docs_metadata = self.docs_metadata[-1].data
                logger.info(f"[LF] Docs metadata is a Data object {self.docs_metadata}")
                additional_metadata.update(self.docs_metadata)
            else:
                for item in self.docs_metadata:
                    if isinstance(item, dict) and "key" in item and "value" in item:
                        additional_metadata[item["key"]] = item["value"]
        # Replace string "None" values with actual None
        for key, value in additional_metadata.items():
            if value == "None":
                additional_metadata[key] = None
        logger.info(f"[LF] Additional metadata {additional_metadata}")
        for doc_obj in docs:
            data_copy = json.loads(doc_obj.model_dump_json())
            text = data_copy.pop(doc_obj.text_key, doc_obj.default_value)
            texts.append(text)

            # Merge additional metadata from table input
            data_copy.update(additional_metadata)

            metadatas.append(data_copy)
        self.log(metadatas)

        # Determine whether the selected embedding is watsonx/IBM. The watsonx
        # SDK ships its own rate-limit machinery (input batching, proactive
        # x-requests-limit-* TokenBucket throttling, and jittered exponential
        # backoff on 429), so we lean on it instead of retrying on top of it.
        # The type-name check also covers watsonx-hosted, non-"ibm/" models
        # (e.g. intfloat/multilingual-e5-large).
        is_ibm = (embedding_model and "ibm" in str(embedding_model).lower()) or (
            selected_embedding and "watsonx" in type(selected_embedding).__name__.lower()
        )
        logger.debug(f"Is IBM/watsonx embedding: {is_ibm}")

        if is_ibm:

            # Hand the full batch to the SDK and let it batch/throttle/retry.
            # Retry attempts and base backoff are tunable via the SDK's own
            # WATSONX_MAX_RETRIES / WATSONX_DELAY_TIME environment variables.
            logger.info(
                f"Embedding {len(texts)} chunks via watsonx SDK batch (SDK-managed throttle + 429 retry)"
            )
            try:
                vectors: list[list[float]] = selected_embedding.embed_documents(texts)
                logger.info(f"Successfully embedded {len(vectors)} chunks via watsonx SDK")
            except Exception as embed_error:
                _log_watsonx_rate_limit_headers(embed_error)
                logger.error(
                    f"Failed to embed {len(texts)} chunks via watsonx SDK. Error: {embed_error}",
                )
                raise

        else:
            # Non-watsonx providers (OpenAI, Ollama) lack the watsonx SDK's
            # built-in rate-limit handling, so embed per chunk in parallel with
            # a generic rate-limit-aware tenacity retry.
            vectors: list[list[float]] = [None] * len(texts)
            from tenacity import (
                retry,
                retry_if_exception,
                stop_after_attempt,
                wait_exponential,
            )

            def is_rate_limit_error(exception: Exception) -> bool:
                """Check if exception is a rate limit error (429)."""
                error_str = str(exception).lower()
                return "429" in error_str or "rate_limit" in error_str or "rate limit" in error_str

            def is_other_retryable_error(exception: Exception) -> bool:
                """Check if exception is a transient network error worth retrying."""
                if is_rate_limit_error(exception):
                    return False
                return isinstance(exception, (ConnectionError, TimeoutError, OSError))

            # Retry decorator for rate limit errors (longer backoff)
            retry_on_rate_limit = retry(
                retry=retry_if_exception(is_rate_limit_error),
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=2, min=2, max=30),
                reraise=True,
                before_sleep=lambda retry_state: logger.warning(
                    f"Rate limit hit for chunk (attempt {retry_state.attempt_number}/5), "
                    f"backing off for {retry_state.next_action.sleep:.1f}s"
                ),
            )

            # Retry decorator for other errors (shorter backoff)
            retry_on_other_errors = retry(
                retry=retry_if_exception(is_other_retryable_error),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                reraise=True,
                before_sleep=lambda retry_state: logger.warning(
                    f"Error embedding chunk (attempt {retry_state.attempt_number}/3), "
                    f"retrying in {retry_state.next_action.sleep:.1f}s: {retry_state.outcome.exception()}"
                ),
            )

            def embed_chunk_with_retry(chunk_text: str, chunk_idx: int) -> list[float]:
                """Embed a single chunk with rate-limit-aware retry logic."""

                @retry_on_rate_limit
                @retry_on_other_errors
                def _embed(text: str) -> list[float]:
                    return selected_embedding.embed_documents([text])[0]

                try:
                    return _embed(chunk_text)
                except Exception as e:
                    logger.error(
                        f"Failed to embed chunk {chunk_idx} after all retries: {e}",
                        error=str(e),
                    )
                    raise

            max_workers = min(max(len(texts), 1), 8)
            logger.debug(f"Using parallel processing with {max_workers} workers")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(embed_chunk_with_retry, chunk, idx): idx
                    for idx, chunk in enumerate(texts)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    vectors[idx] = future.result()

        if not vectors:
            self.log(f"No vectors generated from documents for model {embedding_model}.")
            return

        # Get vector dimension for mapping
        dim = len(vectors[0]) if vectors else 768  # default fallback
        use_openrag_ingest_callback = self._openrag_ingest_callback_config() is not None

        is_aoss = False
        mapping: dict | None = None

        engine = getattr(self, "engine", "jvector")

        if use_openrag_ingest_callback:
            self.log("Using OpenRAG backend ingest callback; skipping direct OpenSearch writes.")
        else:
            # Check for AOSS
            auth_kwargs = self._build_auth_kwargs()
            is_aoss = self._is_aoss_enabled(auth_kwargs.get("http_auth"))

            # Validate engine with AOSS
            self._validate_aoss_with_engines(is_aoss=is_aoss, engine=engine)

            # Create mapping with proper KNN settings
            space_type = getattr(self, "space_type", "l2")
            ef_construction = getattr(self, "ef_construction", 512)
            m = getattr(self, "m", 16)

            mapping = self._default_text_mapping(
                dim=dim,
                engine=engine,
                space_type=space_type,
                ef_construction=ef_construction,
                m=m,
                vector_field=dynamic_field_name,  # Use dynamic field name
            )

            # Ensure index exists with baseline mapping (index.knn: true is required for vector search)
            index_exists = True
            try:
                index_exists = bool(client.indices.exists(index=self.index_name))
            except OpenSearchException as exists_error:
                self._log_index_admin_skip("indices.exists", exists_error)

            try:
                if not index_exists:
                    self.log(f"Creating index '{self.index_name}' with base mapping")
                    client.indices.create(index=self.index_name, body=mapping)
            except RequestError as creation_error:
                if creation_error.error == "resource_already_exists_exception":
                    pass  # Index was created concurrently
                else:
                    error_msg = str(creation_error).lower()
                    if "invalid engine" in error_msg or "illegal_argument" in error_msg:
                        if "jvector" in error_msg:
                            msg = (
                                "The 'jvector' engine is not available in your OpenSearch installation. "
                                "Use 'nmslib' or 'faiss' for standard OpenSearch, or upgrade to 2.9+."
                            )
                            raise ValueError(msg) from creation_error
                        if "index.knn" in error_msg:
                            msg = (
                                "The index has index.knn: false. Delete the existing index and let the "
                                "component recreate it, or create a new index with a different name."
                            )
                            raise ValueError(msg) from creation_error
                    logger.warning(f"Failed to create index '{self.index_name}': {creation_error}")
                    raise

            # Ensure the dynamic field exists in the index
            self._ensure_embedding_field_mapping(
                client=client,
                index_name=self.index_name,
                field_name=dynamic_field_name,
                dim=dim,
                engine=engine,
                space_type=space_type,
                ef_construction=ef_construction,
                m=m,
            )

        self.log(
            f"Indexing {len(texts)} documents into '{self.index_name}' with model '{embedding_model}'..."
        )
        logger.info(f"Will store embeddings in field: {dynamic_field_name}")
        logger.info(f"Will tag documents with embedding_model: {embedding_model}")

        # Use the bulk ingestion with model tracking
        return_ids = self._bulk_ingest_embeddings(
            client=client,
            index_name=self.index_name,
            embeddings=vectors,
            texts=texts,
            metadatas=metadatas,
            vector_field=dynamic_field_name,  # Use dynamic field name
            text_field="text",
            embedding_model=embedding_model,  # Track the model
            mapping=mapping,
            is_aoss=is_aoss,
        )
        self.log(metadatas)

        logger.info(
            f"Ingestion complete: Successfully indexed {len(return_ids)} documents with model '{embedding_model}'"
        )
        self.log(f"Successfully indexed {len(return_ids)} documents with model {embedding_model}.")

    # ---------- helpers for filters ----------
    def _is_placeholder_term(self, term_obj: dict) -> bool:
        # term_obj like {"filename": "__IMPOSSIBLE_VALUE__"}
        return any(v == "__IMPOSSIBLE_VALUE__" for v in term_obj.values())

    def _coerce_filter_clauses(self, filter_obj: dict | None) -> list[dict]:
        """Convert filter expressions into OpenSearch-compatible filter clauses.

        This method accepts two filter formats and converts them to standardized
        OpenSearch query clauses:

        Format A - Explicit filters:
        {"filter": [{"term": {"field": "value"}}, {"terms": {"field": ["val1", "val2"]}}],
         "limit": 10, "score_threshold": 1.5}

        Format B - Context-style mapping:
        {"data_sources": ["file1.pdf"], "document_types": ["pdf"], "owners": ["user1"]}

        Args:
            filter_obj: Filter configuration dictionary or None

        Returns:
            List of OpenSearch filter clauses (term/terms objects)
            Placeholder values with "__IMPOSSIBLE_VALUE__" are ignored
        """
        if not filter_obj:
            return []

        # If it is a string, try to parse it once
        if isinstance(filter_obj, str):
            try:
                filter_obj = json.loads(filter_obj)
            except json.JSONDecodeError:
                # Not valid JSON - treat as no filters
                return []

        # Case A: already an explicit list/dict under "filter"
        if "filter" in filter_obj:
            raw = filter_obj["filter"]
            if isinstance(raw, dict):
                raw = [raw]
            explicit_clauses: list[dict] = []
            for f in raw or []:
                if (
                    "term" in f
                    and isinstance(f["term"], dict)
                    and not self._is_placeholder_term(f["term"])
                ):
                    explicit_clauses.append(f)
                elif "terms" in f and isinstance(f["terms"], dict):
                    field, vals = next(iter(f["terms"].items()))
                    if isinstance(vals, list) and len(vals) > 0:
                        explicit_clauses.append(f)
            return explicit_clauses

        # Case B: convert context-style maps into clauses
        field_mapping = {
            "data_sources": "filename",
            "document_types": "mimetype",
            "owners": "owner",
        }
        context_clauses: list[dict] = []
        for k, values in filter_obj.items():
            if not isinstance(values, list):
                continue
            field = field_mapping.get(k, k)
            if len(values) == 0:
                # Match-nothing placeholder (kept to mirror your tool semantics)
                context_clauses.append({"term": {field: "__IMPOSSIBLE_VALUE__"}})
            elif len(values) == 1:
                if values[0] != "__IMPOSSIBLE_VALUE__":
                    context_clauses.append({"term": {field: values[0]}})
            else:
                context_clauses.append({"terms": {field: values}})
        return context_clauses


    def _parse_filter_expression(self) -> dict | None:
        """Parse and validate optional filter_expression JSON.

        Returns:
            Parsed JSON object as a dict, or None when unset/blank.

        Raises:
            ValueError: If JSON is invalid or does not decode to an object.
        """
        filter_expression = getattr(self, "filter_expression", "")
        if not isinstance(filter_expression, str) or not filter_expression.strip():
            return None
        try:
            filter_obj = json.loads(filter_expression)
        except json.JSONDecodeError as e:
            msg = f"Invalid filter_expression JSON: {e}"
            raise ValueError(msg) from e

        if not isinstance(filter_obj, dict):
            msg = "Invalid filter_expression JSON type: expected a JSON object."
            raise TypeError(msg)
        return filter_obj

    def _resolve_limit(self, filter_obj: dict | None, default_limit: int | None) -> int | None:
        """Resolve an integer result limit from filter settings."""
        if not filter_obj:
            return default_limit
        raw_limit = filter_obj.get("limit", default_limit)
        if raw_limit is None:
            return None
        if isinstance(raw_limit, bool):
            msg = "Invalid filter_expression.limit: expected a positive integer."
            raise TypeError(msg)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as e:
            msg = "Invalid filter_expression.limit: expected a positive integer."
            raise ValueError(msg) from e
        if limit <= 0:
            msg = "Invalid filter_expression.limit: expected a positive integer."
            raise ValueError(msg)
        return limit

    def _resolve_score_threshold(self, filter_obj: dict | None) -> float | None:
        """Resolve optional positive min score from filter settings."""
        if not filter_obj:
            return None
        score_threshold = filter_obj.get("score_threshold")
        if score_threshold is None:
            score_threshold = filter_obj.get("scoreThreshold")
        if not isinstance(score_threshold, (int, float)) or score_threshold <= 0:
            return None
        return float(score_threshold)

    def _detect_available_models(self, client: OpenSearch, filter_clauses: list[dict] | None = None) -> list[str]:

        """Detect which embedding models have documents in the index.

        Uses aggregation to find all unique embedding_model values, optionally
        filtered to only documents matching the user's filter criteria.

        Args:
            client: OpenSearch client instance
            filter_clauses: Optional filter clauses to scope model detection

        Returns:
            List of embedding model names found in the index
        """
        try:
            agg_query = {
                "size": 0,
                "aggs": {"embedding_models": {"terms": {"field": "embedding_model", "size": 10}}},
            }

            # Apply filters to model detection if any exist
            if filter_clauses:
                agg_query["query"] = {"bool": {"filter": filter_clauses}}

            logger.debug(f"Model detection query: {agg_query}")
            result = client.search(
                index=self.index_name,
                body=agg_query,
                params={"terminate_after": 0},
            )
            buckets = result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
            models = [b["key"] for b in buckets if b["key"]]

            # Log detailed bucket info for debugging
            logger.info(
                f"Detected embedding models in corpus: {models}"
                + (f" (with {len(filter_clauses)} filters)" if filter_clauses else "")
            )
            if not models:
                total_hits = result.get("hits", {}).get("total", {})
                total_count = (
                    total_hits.get("value", 0) if isinstance(total_hits, dict) else total_hits
                )
                logger.warning(
                    f"No embedding_model values found in index '{self.index_name}'. "
                    f"Total docs in index: {total_count}. "
                    f"This may indicate documents were indexed without the embedding_model field."
                )
        except (OpenSearchException, KeyError, ValueError) as e:
            logger.warning(f"Failed to detect embedding models: {e}")
            # Fallback to current model
            fallback_model = self._get_embedding_model_name()
            logger.info(f"Using fallback model: {fallback_model}")
            return [fallback_model]
        else:
            return models

    def _get_index_properties(self, client: OpenSearch) -> dict[str, Any] | None:
        """Retrieve flattened mapping properties for the current index."""
        try:
            mapping = client.indices.get_mapping(index=self.index_name)
        except OpenSearchException as e:
            logger.warning(
                f"Failed to fetch mapping for index '{self.index_name}': {e}. Proceeding without mapping metadata."
            )
            return None

        properties: dict[str, Any] = {}
        for index_data in mapping.values():
            props = index_data.get("mappings", {}).get("properties", {})
            if isinstance(props, dict):
                properties.update(props)
        return properties

    def _is_knn_vector_field(self, properties: dict[str, Any] | None, field_name: str) -> bool:
        """Check whether the field is mapped as a knn_vector."""
        if not field_name:
            return False
        if properties is None:
            logger.warning(
                f"Mapping metadata unavailable; assuming field '{field_name}' is usable."
            )
            return True
        field_def = properties.get(field_name)
        if not isinstance(field_def, dict):
            return False
        if field_def.get("type") == "knn_vector":
            return True

        nested_props = field_def.get("properties")
        return bool(isinstance(nested_props, dict) and nested_props.get("type") == "knn_vector")

    def _get_field_dimension(
        self, properties: dict[str, Any] | None, field_name: str
    ) -> int | None:
        """Get the dimension of a knn_vector field from the index mapping.

        Args:
            properties: Index properties from mapping
            field_name: Name of the vector field

        Returns:
            Dimension of the field, or None if not found
        """
        if not field_name or properties is None:
            return None

        field_def = properties.get(field_name)
        if not isinstance(field_def, dict):
            return None

        # Check direct knn_vector field
        if field_def.get("type") == "knn_vector":
            return field_def.get("dimension")

        # Check nested properties
        nested_props = field_def.get("properties")
        if isinstance(nested_props, dict) and nested_props.get("type") == "knn_vector":
            return nested_props.get("dimension")

        return None

    def _get_filename_agg_field(self, index_properties: dict[str, Any] | None) -> str:
        """Choose the appropriate field for filename aggregations."""
        if not index_properties:
            return "filename.keyword"

        filename_def = index_properties.get("filename")
        if not isinstance(filename_def, dict):
            return "filename.keyword"

        field_type = filename_def.get("type")
        fields_def = filename_def.get("fields", {})

        # Top-level keyword with no subfields
        if field_type == "keyword" and not isinstance(fields_def, dict):
            return "filename"

        # Text field with keyword subfield
        if isinstance(fields_def, dict) and "keyword" in fields_def:
            return "filename.keyword"

        # Fallback: aggregate on filename directly
        return "filename"

    # ---------- search (multi-model hybrid) ----------
    def search(self, query: str | None = None) -> list[dict[str, Any]]:
        """Perform multi-model hybrid search combining multiple vector similarities and keyword matching.

        This method executes a sophisticated search that:
        1. Auto-detects all embedding models present in the index
        2. Generates query embeddings for ALL detected models in parallel
        3. Combines multiple KNN queries using dis_max (picks best match)
        4. Adds keyword search with fuzzy matching (30% weight)
        5. Applies optional filtering and score thresholds
        6. Returns aggregations for faceted search

        Search weights:
        - Semantic search (dis_max across all models): 70%
        - Keyword search: 30%

        Args:
            query: Search query string (used for both vector embedding and keyword search)

        Returns:
            List of search results with page_content, metadata, and relevance scores

        Raises:
            ValueError: If embedding component is not provided or filter JSON is invalid
        """
        logger.info(self.ingest_data)
        client = self.build_client()
        q = (query or "").strip()

        # Parse optional filter expression
        filter_obj = self._parse_filter_expression()

        if not self.embedding:
            msg = "Embedding is required to run hybrid search (KNN + keyword)."
            raise ValueError(msg)

        # Check if embedding is None (fail-safe mode)
        if self.embedding is None or (
            isinstance(self.embedding, list) and all(e is None for e in self.embedding)
        ):
            logger.error("Embedding returned None (fail-safe mode enabled). Cannot perform search.")
            return []

        # Build filter clauses first so we can use them in model detection
        filter_clauses = self._coerce_filter_clauses(filter_obj)

        # Detect available embedding models in the index (scoped by filters)
        available_models = self._detect_available_models(client, filter_clauses)

        if not available_models:
            logger.warning("No embedding models found in index, using current model")
            available_models = [self._get_embedding_model_name()]

        # Generate embeddings for ALL detected models
        query_embeddings = {}

        # Normalize embedding to list
        embeddings_list = self.embedding if isinstance(self.embedding, list) else [self.embedding]
        # Filter out None values (fail-safe mode)
        embeddings_list = [e for e in embeddings_list if e is not None]

        if not embeddings_list:
            logger.error(
                "No valid embeddings available after filtering None values (fail-safe mode). Cannot perform search."
            )
            return []

        # Create a comprehensive map of model names to embedding objects
        # Check all possible identifiers (deployment, model, model_id, model_name)
        # Also leverage available_models list from EmbeddingsWithModels
        # Handle duplicate identifiers by creating combined keys
        embedding_by_model = {}
        identifier_conflicts = {}  # Track which identifiers have conflicts

        for idx, emb_obj in enumerate(embeddings_list):
            # Get all possible identifiers for this embedding
            identifiers = []
            deployment = getattr(emb_obj, "deployment", None)
            model = getattr(emb_obj, "model", None)
            model_id = getattr(emb_obj, "model_id", None)
            model_name = getattr(emb_obj, "model_name", None)
            dimensions = getattr(emb_obj, "dimensions", None)
            available_models_attr = getattr(emb_obj, "available_models", None)

            logger.info(
                f"Embedding object {idx}: deployment={deployment}, model={model}, "
                f"model_id={model_id}, model_name={model_name}, dimensions={dimensions}, "
                f"available_models={available_models_attr}"
            )

            # If this embedding has available_models dict, map all models to their dedicated instances
            if available_models_attr and isinstance(available_models_attr, dict):
                logger.info(
                    f"Embedding object {idx} provides {len(available_models_attr)} models via available_models dict"
                )
                for model_name_key, dedicated_embedding in available_models_attr.items():
                    if model_name_key and str(model_name_key).strip():
                        model_str = str(model_name_key).strip()
                        if model_str not in embedding_by_model:
                            # Use the dedicated embedding instance from the dict
                            embedding_by_model[model_str] = dedicated_embedding
                            logger.info(
                                f"Mapped available model '{model_str}' to dedicated embedding instance"
                            )
                        else:
                            # Conflict detected - track it
                            if model_str not in identifier_conflicts:
                                identifier_conflicts[model_str] = [embedding_by_model[model_str]]
                            identifier_conflicts[model_str].append(dedicated_embedding)
                            logger.warning(
                                f"Available model '{model_str}' has conflict - used by multiple embeddings"
                            )

            # Also map traditional identifiers (for backward compatibility)
            if deployment:
                identifiers.append(str(deployment))
            if model:
                identifiers.append(str(model))
            if model_id:
                identifiers.append(str(model_id))
            if model_name:
                identifiers.append(str(model_name))

            # Map all identifiers to this embedding object
            for identifier in identifiers:
                if identifier not in embedding_by_model:
                    embedding_by_model[identifier] = emb_obj
                    logger.info(f"Mapped identifier '{identifier}' to embedding object {idx}")
                else:
                    # Conflict detected - track it
                    if identifier not in identifier_conflicts:
                        identifier_conflicts[identifier] = [embedding_by_model[identifier]]
                    identifier_conflicts[identifier].append(emb_obj)
                    logger.warning(
                        f"Identifier '{identifier}' has conflict - used by multiple embeddings"
                    )

            # For embeddings with model+deployment, create combined identifier
            # This helps when deployment is the same but model differs
            if deployment and model and deployment != model:
                combined_id = f"{deployment}:{model}"
                if combined_id not in embedding_by_model:
                    embedding_by_model[combined_id] = emb_obj
                    logger.info(
                        f"Created combined identifier '{combined_id}' for embedding object {idx}"
                    )

        # Log conflicts
        if identifier_conflicts:
            logger.warning(
                f"Found {len(identifier_conflicts)} conflicting identifiers. "
                f"Consider using combined format 'deployment:model' or specifying unique model names."
            )
            for conflict_id, emb_list in identifier_conflicts.items():
                logger.warning(
                    f"  Conflict on '{conflict_id}': {len(emb_list)} embeddings use this identifier"
                )

        logger.info(f"Generating embeddings for {len(available_models)} models in index")
        logger.info(f"Available embedding identifiers: {list(embedding_by_model.keys())}")
        self.log(f"[SEARCH] Models detected in index: {available_models}")
        self.log(f"[SEARCH] Available embedding identifiers: {list(embedding_by_model.keys())}")

        # Track matching status for debugging
        matched_models = []
        unmatched_models = []

        for model_name in available_models:
            try:
                # Check if we have an embedding object for this model
                if model_name in embedding_by_model:
                    # Use the matching embedding object directly
                    emb_obj = embedding_by_model[model_name]
                    emb_deployment = getattr(emb_obj, "deployment", None)
                    emb_model = getattr(emb_obj, "model", None)
                    emb_model_id = getattr(emb_obj, "model_id", None)
                    emb_dimensions = getattr(emb_obj, "dimensions", None)
                    emb_available_models = getattr(emb_obj, "available_models", None)

                    logger.info(
                        f"Using embedding object for model '{model_name}': "
                        f"deployment={emb_deployment}, model={emb_model}, model_id={emb_model_id}, "
                        f"dimensions={emb_dimensions}"
                    )

                    # Check if this is a dedicated instance from available_models dict
                    if emb_available_models and isinstance(emb_available_models, dict):
                        logger.info(
                            f"Model '{model_name}' using dedicated instance from available_models dict "
                            f"(pre-configured with correct model and dimensions)"
                        )

                    # Use the embedding instance directly - no model switching needed!
                    vec = emb_obj.embed_query(q)
                    query_embeddings[model_name] = vec
                    matched_models.append(model_name)
                    logger.info(
                        f"Generated embedding for model: {model_name} (actual dimensions: {len(vec)})"
                    )
                    self.log(f"[MATCH] Model '{model_name}' - generated {len(vec)}-dim embedding")
                else:
                    # No matching embedding found for this model
                    unmatched_models.append(model_name)
                    logger.warning(
                        f"No matching embedding found for model '{model_name}'. "
                        f"This model will be skipped. Available identifiers: {list(embedding_by_model.keys())}"
                    )
                    self.log(
                        f"[NO MATCH] Model '{model_name}' - available: {list(embedding_by_model.keys())}"
                    )
            except (
                RuntimeError,
                ValueError,
                ConnectionError,
                TimeoutError,
                AttributeError,
                KeyError,
            ) as e:
                logger.warning(f"Failed to generate embedding for {model_name}: {e}")
                self.log(f"[ERROR] Embedding generation failed for '{model_name}': {e}")

        # Log summary of model matching
        logger.info(
            f"Model matching summary: {len(matched_models)} matched, {len(unmatched_models)} unmatched"
        )
        self.log(
            f"[SUMMARY] Model matching: {len(matched_models)} matched, {len(unmatched_models)} unmatched"
        )
        if unmatched_models:
            self.log(f"[WARN] Unmatched models in index: {unmatched_models}")

        if not query_embeddings:
            msg = (
                f"Failed to generate embeddings for any model. "
                f"Index has models: {available_models}, but no matching embedding objects found. "
                f"Available embedding identifiers: {list(embedding_by_model.keys())}"
            )
            self.log(f"[FAIL] Search failed: {msg}")
            raise ValueError(msg)

        index_properties = self._get_index_properties(client)
        legacy_vector_field = getattr(self, "vector_field", "chunk_embedding")

        # Build KNN queries for each model
        embedding_fields: list[str] = []
        knn_queries_with_candidates = []
        knn_queries_without_candidates = []

        raw_num_candidates = getattr(self, "num_candidates", 1000)
        try:
            num_candidates = int(raw_num_candidates) if raw_num_candidates is not None else 0
        except (TypeError, ValueError):
            num_candidates = 0
        use_num_candidates = num_candidates > 0

        for model_name, embedding_vector in query_embeddings.items():
            field_name = get_embedding_field_name(model_name)
            selected_field = field_name
            vector_dim = len(embedding_vector)

            # Only use the expected dynamic field - no legacy fallback
            # This prevents dimension mismatches between models
            if not self._is_knn_vector_field(index_properties, selected_field):
                logger.warning(
                    f"Skipping model {model_name}: field '{field_name}' is not mapped as knn_vector. "
                    f"Documents must be indexed with this embedding model before querying."
                )
                self.log(
                    f"[SKIP] Field '{selected_field}' not a knn_vector - skipping model '{model_name}'"
                )
                continue

            # Validate vector dimensions match the field dimensions
            field_dim = self._get_field_dimension(index_properties, selected_field)
            if field_dim is not None and field_dim != vector_dim:
                logger.error(
                    f"Dimension mismatch for model '{model_name}': "
                    f"Query vector has {vector_dim} dimensions but field '{selected_field}' expects {field_dim}. "
                    f"Skipping this model to prevent search errors."
                )
                self.log(
                    f"[DIM MISMATCH] Model '{model_name}': query={vector_dim} vs field={field_dim} - skipping"
                )
                continue

            logger.info(
                f"Adding KNN query for model '{model_name}': field='{selected_field}', "
                f"query_dims={vector_dim}, field_dims={field_dim or 'unknown'}"
            )
            embedding_fields.append(selected_field)

            base_query = {
                "knn": {
                    selected_field: {
                        "vector": embedding_vector,
                        "k": 50,
                    }
                }
            }

            if use_num_candidates:
                query_with_candidates = copy.deepcopy(base_query)
                query_with_candidates["knn"][selected_field]["num_candidates"] = num_candidates
            else:
                query_with_candidates = base_query

            knn_queries_with_candidates.append(query_with_candidates)
            knn_queries_without_candidates.append(base_query)

        if not knn_queries_with_candidates:
            # No valid fields found - this can happen when:
            # 1. Index is empty (no documents yet)
            # 2. Embedding model has changed and field doesn't exist yet
            # Return empty results instead of failing
            logger.warning(
                "No valid knn_vector fields found for embedding models. "
                "This may indicate an empty index or missing field mappings. "
                "Returning empty search results."
            )
            self.log(
                f"[WARN] No valid KNN queries could be built. "
                f"Query embeddings generated: {list(query_embeddings.keys())}, "
                f"but no matching knn_vector fields found in index."
            )
            return []

        # Build exists filter - document must have at least one embedding field
        exists_any_embedding = {
            "bool": {
                "should": [{"exists": {"field": f}} for f in set(embedding_fields)],
                "minimum_should_match": 1,
            }
        }

        # Combine user filters with exists filter
        all_filters = [*filter_clauses, exists_any_embedding]

        # Get limit and score threshold
        limit = self._resolve_limit(filter_obj, default_limit=self.number_of_results)
        score_threshold = self._resolve_score_threshold(filter_obj)

        # Determine the best aggregation field for filename based on index mapping
        filename_agg_field = self._get_filename_agg_field(index_properties)

        # Build multi-model hybrid query
        body = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "dis_max": {
                                "tie_breaker": 0.0,  # Take only the best match, no blending
                                "boost": 0.7,  # 70% weight for semantic search
                                "queries": knn_queries_with_candidates,
                            }
                        },
                        {
                            "multi_match": {
                                "query": q,
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
            },
            "aggs": {
                "data_sources": {"terms": {"field": filename_agg_field, "size": 20}},
                "document_types": {"terms": {"field": "mimetype", "size": 10}},
                "owners": {"terms": {"field": "owner", "size": 10}},
                "embedding_models": {"terms": {"field": "embedding_model", "size": 10}},
            },
            "_source": [
                "filename",
                "mimetype",
                "page",
                "text",
                "source_url",
                "owner",
                "embedding_model",
                "allowed_users",
                "allowed_groups",
                "allowed_principals",
            ],
            "size": limit,
        }

        if score_threshold is not None:
            body["min_score"] = score_threshold

        logger.info(
            f"Executing multi-model hybrid search with {len(knn_queries_with_candidates)} embedding models: "
            f"{list(query_embeddings.keys())}"
        )
        self.log(
            f"[EXEC] Executing search with {len(knn_queries_with_candidates)} KNN queries, limit={limit}"
        )
        self.log(f"[EXEC] Embedding models used: {list(query_embeddings.keys())}")
        self.log(f"[EXEC] KNN fields being queried: {embedding_fields}")

        try:
            resp = client.search(index=self.index_name, body=body, params={"terminate_after": 0})
        except RequestError as e:
            error_message = str(e)
            lowered = error_message.lower()
            if use_num_candidates and "num_candidates" in lowered:
                logger.warning(
                    "Retrying search without num_candidates parameter due to cluster capabilities",
                    error=error_message,
                )
                fallback_body = copy.deepcopy(body)
                try:
                    fallback_body["query"]["bool"]["should"][0]["dis_max"]["queries"] = (
                        knn_queries_without_candidates
                    )
                except (KeyError, IndexError, TypeError) as inner_err:
                    raise e from inner_err
                resp = client.search(
                    index=self.index_name,
                    body=fallback_body,
                    params={"terminate_after": 0},
                )
            elif "knn_vector" in lowered or ("field" in lowered and "knn" in lowered):
                fallback_vector = next(iter(query_embeddings.values()), None)
                if fallback_vector is None:
                    raise
                fallback_field = legacy_vector_field or "chunk_embedding"
                logger.warning(
                    "KNN search failed for dynamic fields; falling back to legacy field '%s'.",
                    fallback_field,
                )
                fallback_body = copy.deepcopy(body)
                fallback_body["query"]["bool"]["filter"] = filter_clauses
                knn_fallback = {
                    "knn": {
                        fallback_field: {
                            "vector": fallback_vector,
                            "k": 50,
                        }
                    }
                }
                if use_num_candidates:
                    knn_fallback["knn"][fallback_field]["num_candidates"] = num_candidates
                fallback_body["query"]["bool"]["should"][0]["dis_max"]["queries"] = [knn_fallback]
                resp = client.search(
                    index=self.index_name,
                    body=fallback_body,
                    params={"terminate_after": 0},
                )
            else:
                raise
        hits = resp.get("hits", {}).get("hits", [])

        logger.info(f"Found {len(hits)} results")
        self.log(f"[RESULT] Search complete: {len(hits)} results found")

        if len(hits) == 0:
            self.log(
                f"[EMPTY] Debug info: "
                f"models_in_index={available_models}, "
                f"matched_models={matched_models}, "
                f"knn_fields={embedding_fields}, "
                f"filters={len(filter_clauses)} clauses"
            )

        return [
            {
                "page_content": hit["_source"].get("text", ""),
                "metadata": {k: v for k, v in hit["_source"].items() if k != "text"},
                "score": hit.get("_score"),
            }
            for hit in hits
        ]

    def search_documents(self) -> Table:

        """Search documents and return results as a Table.

        This is the main interface method that performs the multi-model search using the
        configured search_query and returns results in Langflow's Table (DataFrame) format
        so downstream Parser components can consume them directly.

        Always builds the vector store (triggering ingestion if needed), then performs
        search only if a query is provided.

        Returns:
            Table containing search results with text and metadata

        Raises:
            Exception: If search operation fails
        """

        try:
            # Always build/cache the vector store to ensure ingestion happens
            logger.info(f"Search query: {self.search_query}")
            if self._cached_vector_store is None:
                self.build_vector_store()

            # Only perform search if query is provided
            search_query = (self.search_query or "").strip()
            if not search_query:
                self.log("No search query provided - ingestion completed, returning empty results")

                return Table(data=[])

            # Perform search with the provided query
            raw = self.search(search_query)
            raw_list = [Data(text=hit["page_content"], **hit["metadata"]) for hit in raw]
            return Table(data=raw_list)

        except Exception as e:
            self.log(f"search_documents error: {e}")
            raise

    # -------- dynamic UI handling (auth switch) --------
    async def update_build_config(
        self, build_config: dict, field_value: str, field_name: str | None = None
    ) -> dict:
        """Dynamically update component configuration based on field changes.

        This method handles real-time UI updates, particularly for authentication
        mode changes that show/hide relevant input fields.

        Args:
            build_config: Current component configuration
            field_value: New value for the changed field
            field_name: Name of the field that changed

        Returns:
            Updated build configuration with appropriate field visibility
        """
        try:
            if field_name == "auth_mode":
                mode = (field_value or "basic").strip().lower()
                is_basic = mode == "basic"
                is_jwt = mode == "jwt"
                is_openrag = mode == "openrag"

                build_config["username"]["show"] = is_basic
                build_config["password"]["show"] = is_basic

                build_config["jwt_token"]["show"] = is_jwt
                build_config["jwt_header"]["show"] = is_jwt
                build_config["bearer_prefix"]["show"] = is_jwt

                build_config["username"]["required"] = is_basic
                build_config["password"]["required"] = is_basic

                # build_config["jwt_token"]["required"] = is_jwt
                build_config["jwt_header"]["required"] = is_jwt
                build_config["bearer_prefix"]["required"] = False

                # In 'openrag' mode, expose the OPENRAG_* fields up front
                # since they are the only credentials required.
                for openrag_field in (
                    "openrag_ingest_url",
                    "openrag_ingest_token",
                    "openrag_ingest_run_id",
                    "openrag_ingest_batch_size",
                ):
                    if openrag_field in build_config:
                        build_config[openrag_field]["advanced"] = not is_openrag
                        build_config[openrag_field]["required"] = (
                            is_openrag and openrag_field != "openrag_ingest_batch_size"
                        )

                if is_basic or is_openrag:
                    build_config["jwt_token"]["value"] = ""

                return build_config

        except (KeyError, ValueError) as e:
            self.log(f"update_build_config error: {e}")

        return build_config
