from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.documents import Document

from lfx.base.vectorstores.model import LCVectorStoreComponent, check_cached_vector_store
from lfx.base.vectorstores.vector_store_connection_decorator import vector_store_connection
from lfx.io import (
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
from lfx.serialization import serialize


def _normalize_runtime_value(value: Any) -> Any:
    """Resolve env-backed defaults while preserving explicit runtime values."""
    if not isinstance(value, str):
        return value

    normalized = value.strip()
    if not normalized:
        return normalized

    env_value = os.getenv(normalized)
    if env_value not in (None, ""):
        return env_value
    return normalized


@vector_store_connection
class OpenSearchVectorStoreComponentMultimodalMultiEmbedding(LCVectorStoreComponent):
    """Astra-backed replacement that preserves the existing OpenRAG flow interface."""

    display_name: str = "Astra DB (Multi-Model Compatible)"
    icon: str = "AstraDB"
    description: str = (
        "Store and search documents using Astra DB while preserving the OpenRAG "
        "multi-embedding-compatible flow interface."
    )
    documentation: str = "https://docs.langflow.org/bundles-datastax"

    default_keys: list[str] = [
        "docs_metadata",
        "token",
        "api_endpoint",
        "keyspace",
        "collection_name",
        "index_name",
        *[i.name for i in LCVectorStoreComponent.inputs],
        "embedding",
        "embedding_model_name",
        "vector_field",
        "number_of_results",
        "filter_expression",
    ]

    inputs = [
        TableInput(
            name="docs_metadata",
            display_name="Document Metadata",
            info="Additional metadata key-value pairs to add to all ingested documents.",
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
            input_types=["Data"],
        ),
        SecretStrInput(
            name="token",
            display_name="Astra DB Application Token",
            value="ASTRA_DB_APPLICATION_TOKEN",
            load_from_db=False,
            info="Astra DB application token or the env var name that provides it.",
        ),
        StrInput(
            name="api_endpoint",
            display_name="Astra DB API Endpoint",
            value="ASTRA_DB_API_ENDPOINT",
            info="Astra DB API endpoint or the env var name that provides it.",
        ),
        StrInput(
            name="keyspace",
            display_name="Astra DB Keyspace",
            value="ASTRA_DB_KEYSPACE",
            advanced=True,
            info=(
                "Optional Astra DB keyspace/namespace or the env var name that provides it. "
                "Leave empty to use Astra's default keyspace."
            ),
        ),
        StrInput(
            name="collection_name",
            display_name="Collection Name",
            value="OPENSEARCH_INDEX_NAME",
            info="Collection to use for Astra DB storage and retrieval.",
        ),
        StrInput(
            name="index_name",
            display_name="Legacy Index Name Alias",
            value="OPENSEARCH_INDEX_NAME",
            advanced=True,
            info="Compatibility alias used by OpenRAG; maps to the Astra collection name.",
        ),
        *LCVectorStoreComponent.inputs,
        HandleInput(
            name="embedding",
            display_name="Embedding",
            input_types=["Embeddings"],
            is_list=True,
        ),
        StrInput(
            name="embedding_model_name",
            display_name="Embedding Model Name",
            value="",
            info=(
                "Embedding identifier to use from the connected embeddings. "
                "Matches deployment, model, model_id, model_name, or available_models keys."
            ),
        ),
        StrInput(
            name="vector_field",
            display_name="Legacy Vector Field Name",
            value="chunk_embedding",
            advanced=True,
            info="Compatibility field retained for flow parity; unused by Astra DB.",
        ),
        IntInput(
            name="number_of_results",
            display_name="Default Result Limit",
            value=10,
            advanced=True,
        ),
        MultilineInput(
            name="filter_expression",
            display_name="Search Filters (JSON)",
            value="",
            info=(
                "Optional JSON filters. Supports the existing OpenRAG explicit filter format "
                "and the context-style mapping format."
            ),
        ),
    ]

    outputs = [
        Output(display_name="Search Results", name="search_results", method="search_documents"),
        Output(display_name="Raw Search", name="raw_search", method="raw_search"),
    ]

    def _resolve_collection_name(self) -> str:
        collection_name = _normalize_runtime_value(
            getattr(self, "collection_name", None) or getattr(self, "index_name", None)
        )
        if not collection_name:
            raise ValueError("Astra DB collection name is required.")
        return str(collection_name)

    def _resolve_token(self) -> str:
        token = _normalize_runtime_value(getattr(self, "token", None))
        if not token:
            raise ValueError("Astra DB application token is required.")
        return str(token)

    def _resolve_api_endpoint(self) -> str:
        api_endpoint = _normalize_runtime_value(getattr(self, "api_endpoint", None))
        if not api_endpoint:
            raise ValueError("Astra DB API endpoint is required.")
        return str(api_endpoint)

    def _resolve_keyspace(self) -> str | None:
        keyspace = _normalize_runtime_value(getattr(self, "keyspace", None))
        if not keyspace:
            return None
        return str(keyspace)

    def _normalize_docs_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        docs_metadata = getattr(self, "docs_metadata", None) or []

        if isinstance(docs_metadata, list) and docs_metadata and isinstance(docs_metadata[-1], Data):
            trailing_data = docs_metadata[-1].data
            if isinstance(trailing_data, dict):
                metadata.update(trailing_data)
            docs_metadata = docs_metadata[:-1]

        for item in docs_metadata:
            if isinstance(item, dict) and "key" in item and "value" in item:
                metadata[item["key"]] = item["value"]

        for key, value in list(metadata.items()):
            if value == "None":
                metadata[key] = None

        return metadata

    def _get_embedding_identifiers(self, embedding_obj: Any) -> list[str]:
        identifiers: list[str] = []
        for attr_name in ("deployment", "model", "model_id", "model_name"):
            attr_value = getattr(embedding_obj, attr_name, None)
            if attr_value:
                identifiers.append(str(attr_value))

        deployment = getattr(embedding_obj, "deployment", None)
        model = getattr(embedding_obj, "model", None)
        if deployment and model and deployment != model:
            identifiers.append(f"{deployment}:{model}")

        available_models = getattr(embedding_obj, "available_models", None)
        if isinstance(available_models, dict):
            for model_name in available_models:
                if model_name:
                    identifiers.append(str(model_name))

        seen: set[str] = set()
        return [identifier for identifier in identifiers if not (identifier in seen or seen.add(identifier))]

    def _configured_embedding_target(self) -> str | None:
        candidate_values = [
            getattr(self, "embedding_model_name", None),
            os.getenv("EMBEDDING_MODEL"),
            os.getenv("SELECTED_EMBEDDING_MODEL"),
        ]
        for value in candidate_values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _select_embedding(self) -> tuple[Any, str]:
        if not self.embedding:
            raise ValueError("Embedding handle is required to use the Astra DB component.")

        embeddings = self.embedding if isinstance(self.embedding, list) else [self.embedding]
        embeddings = [embedding for embedding in embeddings if embedding is not None]
        if not embeddings:
            raise ValueError("No valid embeddings were provided to the Astra DB component.")

        embedding_by_identifier: dict[str, Any] = {}
        for embedding_obj in embeddings:
            for identifier in self._get_embedding_identifiers(embedding_obj):
                if identifier not in embedding_by_identifier:
                    embedding_by_identifier[identifier] = embedding_obj

            available_models = getattr(embedding_obj, "available_models", None)
            if isinstance(available_models, dict):
                for model_name, dedicated_embedding in available_models.items():
                    if model_name and model_name not in embedding_by_identifier:
                        embedding_by_identifier[str(model_name)] = dedicated_embedding

        target = self._configured_embedding_target()
        if target:
            if target in embedding_by_identifier:
                selected_embedding = embedding_by_identifier[target]
                return selected_embedding, self._get_embedding_model_name(selected_embedding, fallback=target)

            available = ", ".join(sorted(embedding_by_identifier))
            raise ValueError(
                f"Embedding model '{target}' was not found in the connected embeddings. "
                f"Available identifiers: {available}"
            )

        selected_embedding = embeddings[0]
        return selected_embedding, self._get_embedding_model_name(selected_embedding)

    def _get_embedding_model_name(self, embedding_obj: Any = None, fallback: str | None = None) -> str:
        explicit = getattr(self, "embedding_model_name", None)
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        if fallback:
            return fallback

        if embedding_obj is not None:
            for attr_name in ("deployment", "model", "model_id", "model_name"):
                attr_value = getattr(embedding_obj, attr_name, None)
                if attr_value:
                    return str(attr_value)

        env_model = self._configured_embedding_target()
        if env_model:
            return env_model

        raise ValueError("Could not determine the active embedding model name for Astra DB.")

    def _prepare_documents(self, embedding_model: str) -> list[Document]:
        self.ingest_data = self._prepare_ingest_data()
        docs = self.ingest_data or []
        if not docs:
            return []

        additional_metadata = self._normalize_docs_metadata()
        documents: list[Document] = []

        for item in docs:
            if not isinstance(item, Data):
                raise TypeError("Vector Store inputs must be Data objects.")

            lc_doc = item.to_lc_document()
            metadata = serialize(lc_doc.metadata, to_str=True) if lc_doc.metadata else {}
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.update(additional_metadata)
            metadata.setdefault("embedding_model", embedding_model)
            documents.append(Document(page_content=lc_doc.page_content, metadata=metadata))

        return documents

    def _build_filter_payload(self, raw_filter: Any = None) -> tuple[dict[str, Any], int, float | None]:
        payload = raw_filter if raw_filter is not None else getattr(self, "filter_expression", "")

        if not payload:
            return {}, int(getattr(self, "number_of_results", 10) or 10), None

        if isinstance(payload, str):
            payload = payload.strip()
            if not payload:
                return {}, int(getattr(self, "number_of_results", 10) or 10), None
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid filter_expression JSON: {exc}") from exc

        if not isinstance(payload, dict):
            return {}, int(getattr(self, "number_of_results", 10) or 10), None

        filter_dict = self._coerce_filter_dict(payload)
        limit = payload.get("limit", getattr(self, "number_of_results", 10) or 10)
        score_threshold = payload.get("score_threshold", payload.get("scoreThreshold"))
        return filter_dict, int(limit), score_threshold

    def _coerce_filter_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        clauses: list[dict[str, Any]] = []

        if "filter" in payload:
            raw_filters = payload.get("filter")
            if isinstance(raw_filters, dict):
                raw_filters = [raw_filters]
            for entry in raw_filters or []:
                if not isinstance(entry, dict):
                    continue
                if "term" in entry and isinstance(entry["term"], dict):
                    field, value = next(iter(entry["term"].items()))
                    clauses.append({field: value})
                elif "terms" in entry and isinstance(entry["terms"], dict):
                    field, values = next(iter(entry["terms"].items()))
                    if isinstance(values, list) and values:
                        clauses.append({field: {"$in": values}})
        else:
            field_mapping = {
                "data_sources": "filename",
                "document_types": "mimetype",
                "owners": "owner",
            }
            for key, values in payload.items():
                if key in {"limit", "score_threshold", "scoreThreshold"}:
                    continue
                if not isinstance(values, list):
                    continue
                mapped_key = field_mapping.get(key, key)
                if len(values) == 1:
                    clauses.append({mapped_key: values[0]})
                elif len(values) > 1:
                    clauses.append({mapped_key: {"$in": values}})

        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    @check_cached_vector_store
    def build_vector_store(self):
        try:
            from langchain_astradb import AstraDBVectorStore
        except ImportError as exc:
            raise ImportError(
                "Could not import the Astra DB LangChain integration. "
                "Please install `langchain-astradb` in the Langflow runtime."
            ) from exc

        selected_embedding, embedding_model = self._select_embedding()
        vector_store = AstraDBVectorStore(
            token=self._resolve_token(),
            api_endpoint=self._resolve_api_endpoint(),
            collection_name=self._resolve_collection_name(),
            namespace=self._resolve_keyspace(),
            embedding=selected_embedding,
        )

        documents = self._prepare_documents(embedding_model)
        if documents:
            logger.info(
                "Adding documents to Astra DB collection",
                collection_name=self._resolve_collection_name(),
                document_count=len(documents),
                embedding_model=embedding_model,
            )
            vector_store.add_documents(documents)

        return vector_store

    def search(self, query: str | None = None, filter_source: Any = None) -> list[dict[str, Any]]:
        vector_store = self._cached_vector_store or self.build_vector_store()
        query_value = (query or "").strip()
        filter_dict, limit, score_threshold = self._build_filter_payload(filter_source)
        filter_arg = filter_dict or None

        documents_with_scores: list[tuple[Document, float]] | None = None
        documents: list[Document] = []

        if query_value:
            if score_threshold is not None and hasattr(vector_store, "similarity_search_with_relevance_scores"):
                documents_with_scores = vector_store.similarity_search_with_relevance_scores(
                    query_value,
                    k=limit,
                    filter=filter_arg,
                )
            elif score_threshold is not None and hasattr(vector_store, "similarity_search_with_score"):
                documents_with_scores = vector_store.similarity_search_with_score(
                    query_value,
                    k=limit,
                    filter=filter_arg,
                )
            else:
                documents = vector_store.similarity_search(
                    query_value,
                    k=limit,
                    filter=filter_arg,
                )
        elif filter_arg and hasattr(vector_store, "metadata_search"):
            documents = vector_store.metadata_search(filter=filter_arg, n=limit)

        if documents_with_scores is not None:
            results = []
            for document, score in documents_with_scores:
                if score_threshold is not None and isinstance(score, (int, float)) and score < score_threshold:
                    continue
                results.append(
                    {
                        "page_content": document.page_content,
                        "metadata": document.metadata,
                        "score": score,
                    }
                )
            return results

        return [
            {
                "page_content": document.page_content,
                "metadata": document.metadata,
                "score": None,
            }
            for document in documents
        ]

    def search_documents(self) -> list[Data]:
        search_query = (getattr(self, "search_query", "") or "").strip()
        raw_results = self.search(search_query)
        return [Data(text=result["page_content"], **result["metadata"]) for result in raw_results]

    def raw_search(self, query: str | dict | None = None) -> Data:
        raw_query = query if query is not None else getattr(self, "search_query", "")
        filter_source = None
        search_query = ""

        if isinstance(raw_query, dict):
            search_query = str(raw_query.get("search_query") or raw_query.get("query") or "").strip()
            filter_source = raw_query if "filter" in raw_query else None
        elif isinstance(raw_query, str):
            search_query = raw_query.strip()
        else:
            raise TypeError(f"Unsupported raw_search query type: {type(raw_query)!r}")

        filter_dict, limit, score_threshold = self._build_filter_payload(filter_source)
        return Data(
            data={
                "results": self.search(search_query, filter_source=filter_source),
                "query": search_query,
                "filter": filter_dict,
                "limit": limit,
                "score_threshold": score_threshold,
                "collection_name": self._resolve_collection_name(),
            }
        )

    async def update_build_config(
        self,
        build_config: dict,
        field_value: str | dict,
        field_name: str | None = None,
    ) -> dict:
        return build_config
