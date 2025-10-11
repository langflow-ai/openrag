from __future__ import annotations

import copy
import json
import time
import uuid
from typing import Any, List, Optional

from concurrent.futures import ThreadPoolExecutor, as_completed

from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import RequestError

from lfx.base.vectorstores.model import LCVectorStoreComponent, check_cached_vector_store
from lfx.base.vectorstores.vector_store_connection_decorator import vector_store_connection
from lfx.io import BoolInput, DropdownInput, HandleInput, IntInput, MultilineInput, SecretStrInput, StrInput, TableInput
from lfx.log import logger
from lfx.schema.data import Data


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
    return f"chunk_embedding_{normalize_model_name(model_name)}"


@vector_store_connection
class OpenSearchVectorStoreComponent(LCVectorStoreComponent):
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
    """

    display_name: str = "OpenSearch (Multi-Model)"
    icon: str = "OpenSearch"
    description: str = (
        "Store and search documents using OpenSearch with multi-model hybrid semantic and keyword search."
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
    ]

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
            input_types=["Data"]
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
            options=["jvector", "nmslib", "faiss", "lucene"],
            value="jvector",
            info=(
                "Vector search engine for similarity calculations. 'jvector' is recommended for most use cases. "
                "Note: Amazon OpenSearch Serverless only supports 'nmslib' or 'faiss'."
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
        HandleInput(name="embedding", display_name="Embedding", input_types=["Embeddings"]),
        StrInput(
            name="embedding_model_name",
            display_name="Embedding Model Name",
            value="",
            info=(
                "Name of the embedding model being used (e.g., 'text-embedding-3-small'). "
                "Used to create dynamic vector field names and track which model embedded each document. "
                "Auto-detected from embedding component if not specified."
            ),
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
            value="basic",
            options=["basic", "jwt"],
            info=(
                "Authentication method: 'basic' for username/password authentication, "
                "or 'jwt' for JSON Web Token (Bearer) authentication."
            ),
            real_time_refresh=True,
            advanced=False,
        ),
        StrInput(
            name="username",
            display_name="Username",
            value="admin",
            show=False,
        ),
        SecretStrInput(
            name="password",
            display_name="OpenSearch Password",
            value="admin",
            show=False,
        ),
        SecretStrInput(
            name="jwt_token",
            display_name="JWT Token",
            value="JWT",
            load_from_db=False,
            show=True,
            info=(
                "Valid JSON Web Token for authentication. "
                "Will be sent in the Authorization header (with optional 'Bearer ' prefix)."
            ),
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
            value=True,
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
    ]

    def _get_embedding_model_name(self) -> str:
        """Get the embedding model name from component config or embedding object.

        Returns:
            Embedding model name

        Raises:
            ValueError: If embedding model name cannot be determined
        """
        # First try explicit embedding_model_name input
        if hasattr(self, "embedding_model_name") and self.embedding_model_name:
            return self.embedding_model_name.strip()

        # Try to get from embedding component
        if hasattr(self, "embedding") and self.embedding:
            if hasattr(self.embedding, "model"):
                return str(self.embedding.model)
            if hasattr(self.embedding, "model_name"):
                return str(self.embedding.model_name)

        msg = (
            "Could not determine embedding model name. "
            "Please set the 'embedding_model_name' field or ensure the embedding component "
            "has a 'model' or 'model_name' attribute."
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
                    "embedding_model": {
                        "type": "keyword"
                    },
                    "embedding_dimensions": {
                        "type": "integer"
                    }
                }
            }
            client.indices.put_mapping(index=index_name, body=mapping)
            logger.info(f"Added/updated embedding field mapping: {field_name}")
        except Exception as e:
            logger.warning(f"Could not add embedding field mapping for {field_name}: {e}")
            raise

        properties = self._get_index_properties(client)
        if not self._is_knn_vector_field(properties, field_name):
            raise ValueError(
                f"Field '{field_name}' is not mapped as knn_vector. Current mapping: {properties.get(field_name)}"
            )

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
        return http_auth is not None and hasattr(http_auth, "service") and http_auth.service == "aoss"

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
        if not mapping:
            mapping = {}

        requests = []
        return_ids = []
        vector_dimensions = len(embeddings[0]) if embeddings else None

        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas else {}
            if vector_dimensions is not None and "embedding_dimensions" not in metadata:
                metadata = {**metadata, "embedding_dimensions": vector_dimensions}
            _id = ids[i] if ids else str(uuid.uuid4())
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
        helpers.bulk(client, requests, max_chunk_bytes=max_chunk_bytes)
        return return_ids

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
        auth_kwargs = self._build_auth_kwargs()
        return OpenSearch(
            hosts=[self.opensearch_url],
            use_ssl=self.use_ssl,
            verify_certs=self.verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            **auth_kwargs,
        )

    @check_cached_vector_store
    def build_vector_store(self) -> OpenSearch:
        # Return raw OpenSearch client as our "vector store."
        self.log(self.ingest_data)
        client = self.build_client()
        self._add_documents_to_vector_store(client=client)
        return client

    # ---------- ingest ----------
    def _add_documents_to_vector_store(self, client: OpenSearch) -> None:
        """Process and ingest documents into the OpenSearch vector store.

        This method handles the complete document ingestion pipeline:
        - Prepares document data and metadata
        - Generates vector embeddings
        - Creates appropriate index mappings with dynamic field names
        - Bulk inserts documents with vectors and model tracking

        Args:
            client: OpenSearch client for performing operations
        """
        # Convert DataFrame to Data if needed using parent's method
        self.ingest_data = self._prepare_ingest_data()

        docs = self.ingest_data or []
        if not docs:
            self.log("No documents to ingest.")
            return

        # Get embedding model name
        embedding_model = self._get_embedding_model_name()
        dynamic_field_name = get_embedding_field_name(embedding_model)

        self.log(f"Using embedding model: {embedding_model}")
        self.log(f"Dynamic vector field: {dynamic_field_name}")

        # Extract texts and metadata from documents
        texts = []
        metadatas = []
        # Process docs_metadata table input into a dict
        additional_metadata = {}
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
        if not self.embedding:
            msg = "Embedding handle is required to embed documents."
            raise ValueError(msg)

        # Generate embeddings (threaded for concurrency) with retries
        def embed_chunk(chunk_text: str) -> list[float]:
            return self.embedding.embed_documents([chunk_text])[0]

        vectors: Optional[List[List[float]]] = None
        last_exception: Optional[Exception] = None
        delay = 1.0
        attempts = 0

        while attempts < 3:
            attempts += 1
            try:
                max_workers = min(max(len(texts), 1), 8)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(embed_chunk, chunk): idx for idx, chunk in enumerate(texts)}
                    vectors = [None] * len(texts)
                    for future in as_completed(futures):
                        idx = futures[future]
                        vectors[idx] = future.result()
                break
            except Exception as exc:
                last_exception = exc
                if attempts >= 3:
                    logger.error(
                        "Embedding generation failed after retries",
                        error=str(exc),
                    )
                    raise
                logger.warning(
                    "Threaded embedding generation failed (attempt %s/%s), retrying in %.1fs",
                    attempts,
                    3,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 8.0)

        if vectors is None:
            raise RuntimeError(
                f"Embedding generation failed: {last_exception}" if last_exception else "Embedding generation failed"
            )

        if not vectors:
            self.log("No vectors generated from documents.")
            return

        # Get vector dimension for mapping
        dim = len(vectors[0]) if vectors else 768  # default fallback

        # Check for AOSS
        auth_kwargs = self._build_auth_kwargs()
        is_aoss = self._is_aoss_enabled(auth_kwargs.get("http_auth"))

        # Validate engine with AOSS
        engine = getattr(self, "engine", "jvector")
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

        # Ensure index exists with baseline mapping
        try:
            if not client.indices.exists(index=self.index_name):
                self.log(f"Creating index '{self.index_name}' with base mapping")
                client.indices.create(index=self.index_name, body=mapping)
        except RequestError as creation_error:
            if creation_error.error != "resource_already_exists_exception":
                logger.warning(
                    f"Failed to create index '{self.index_name}': {creation_error}"
                )

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

        self.log(f"Indexing {len(texts)} documents into '{self.index_name}' with model '{embedding_model}'...")

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
                if "term" in f and isinstance(f["term"], dict) and not self._is_placeholder_term(f["term"]):
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

    def _detect_available_models(self, client: OpenSearch, filter_clauses: list[dict] = None) -> list[str]:
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

            result = client.search(
                index=self.index_name,
                body=agg_query,
                params={"terminate_after": 0},
            )
            buckets = result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
            models = [b["key"] for b in buckets if b["key"]]

            logger.info(
                f"Detected embedding models in corpus: {models}"
                + (f" (with {len(filter_clauses)} filters)" if filter_clauses else "")
            )
            return models
        except Exception as e:
            logger.warning(f"Failed to detect embedding models: {e}")
            # Fallback to current model
            return [self._get_embedding_model_name()]

    def _get_index_properties(self, client: OpenSearch) -> dict[str, Any] | None:
        """Retrieve flattened mapping properties for the current index."""
        try:
            mapping = client.indices.get_mapping(index=self.index_name)
        except Exception as e:
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
        if isinstance(nested_props, dict) and nested_props.get("type") == "knn_vector":
            return True

        return False

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
        filter_obj = None
        if getattr(self, "filter_expression", "") and self.filter_expression.strip():
            try:
                filter_obj = json.loads(self.filter_expression)
            except json.JSONDecodeError as e:
                msg = f"Invalid filter_expression JSON: {e}"
                raise ValueError(msg) from e

        if not self.embedding:
            msg = "Embedding is required to run hybrid search (KNN + keyword)."
            raise ValueError(msg)

        # Build filter clauses first so we can use them in model detection
        filter_clauses = self._coerce_filter_clauses(filter_obj)

        # Detect available embedding models in the index (scoped by filters)
        available_models = self._detect_available_models(client, filter_clauses)

        if not available_models:
            logger.warning("No embedding models found in index, using current model")
            available_models = [self._get_embedding_model_name()]

        # Generate embeddings for ALL detected models in parallel
        query_embeddings = {}

        # Note: Langflow is synchronous, so we can't use true async here
        # But we log the intent for parallel processing
        logger.info(f"Generating embeddings for {len(available_models)} models")

        for model_name in available_models:
            try:
                # In a real async environment, these would run in parallel
                # For now, they run sequentially
                vec = self.embedding.embed_query(q)
                query_embeddings[model_name] = vec
                logger.info(f"Generated embedding for model: {model_name}")
            except Exception as e:
                logger.error(f"Failed to generate embedding for {model_name}: {e}")

        if not query_embeddings:
            msg = "Failed to generate embeddings for any model"
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

            # Only use the expected dynamic field - no legacy fallback
            # This prevents dimension mismatches between models
            if not self._is_knn_vector_field(index_properties, selected_field):
                logger.warning(
                    f"Skipping model {model_name}: field '{field_name}' is not mapped as knn_vector. "
                    f"Documents must be indexed with this embedding model before querying."
                )
                continue

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
            return []

        # Build exists filter - document must have at least one embedding field
        exists_any_embedding = {
            "bool": {
                "should": [{"exists": {"field": f}} for f in set(embedding_fields)],
                "minimum_should_match": 1
            }
        }

        # Combine user filters with exists filter
        all_filters = [*filter_clauses, exists_any_embedding]

        # Get limit and score threshold
        limit = (filter_obj or {}).get("limit", self.number_of_results)
        score_threshold = (filter_obj or {}).get("score_threshold", 0)

        # Build multi-model hybrid query
        body = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "dis_max": {
                                "tie_breaker": 0.0,  # Take only the best match, no blending
                                "boost": 0.7,  # 70% weight for semantic search
                                "queries": knn_queries_with_candidates
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
                "data_sources": {"terms": {"field": "filename", "size": 20}},
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
            ],
            "size": limit,
        }

        if isinstance(score_threshold, (int, float)) and score_threshold > 0:
            body["min_score"] = score_threshold

        logger.info(
            f"Executing multi-model hybrid search with {len(knn_queries_with_candidates)} embedding models"
        )

        try:
            resp = client.search(
                index=self.index_name, body=body, params={"terminate_after": 0}
            )
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
                    fallback_body["query"]["bool"]["should"][0]["dis_max"]["queries"] = knn_queries_without_candidates
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

        return [
            {
                "page_content": hit["_source"].get("text", ""),
                "metadata": {k: v for k, v in hit["_source"].items() if k != "text"},
                "score": hit.get("_score"),
            }
            for hit in hits
        ]

    def search_documents(self) -> list[Data]:
        """Search documents and return results as Data objects.

        This is the main interface method that performs the multi-model search using the
        configured search_query and returns results in Langflow's Data format.

        Returns:
            List of Data objects containing search results with text and metadata

        Raises:
            Exception: If search operation fails
        """
        try:
            raw = self.search(self.search_query or "")
            return [Data(text=hit["page_content"], **hit["metadata"]) for hit in raw]
            self.log(self.ingest_data)
        except Exception as e:
            self.log(f"search_documents error: {e}")
            raise

    # -------- dynamic UI handling (auth switch) --------
    async def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None) -> dict:
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

                build_config["username"]["show"] = is_basic
                build_config["password"]["show"] = is_basic

                build_config["jwt_token"]["show"] = is_jwt
                build_config["jwt_header"]["show"] = is_jwt
                build_config["bearer_prefix"]["show"] = is_jwt

                build_config["username"]["required"] = is_basic
                build_config["password"]["required"] = is_basic

                build_config["jwt_token"]["required"] = is_jwt
                build_config["jwt_header"]["required"] = is_jwt
                build_config["bearer_prefix"]["required"] = False

                if is_basic:
                    build_config["jwt_token"]["value"] = ""

                return build_config

        except (KeyError, ValueError) as e:
            self.log(f"update_build_config error: {e}")

        return build_config
