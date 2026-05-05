import os
from collections import Counter
from typing import Any, Awaitable, Callable, Dict

from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
from config.settings import get_embedding_model, get_index_name
from services.knowledge_access import KnowledgeAccessContext
from services.knowledge_backend import KnowledgeBackend
from utils.file_utils import get_filename_aliases
from utils.logging_config import get_logger

logger = get_logger(__name__)

SearchEmbeddingFn = Callable[[str, str], Awaitable[list[float]]]

_RESERVED_DOCUMENT_FIELDS = {
    "_id",
    "content",
    "metadata",
    "$vector",
    "$vectorize",
    "$lexical",
    "$similarity",
}


class AstraDBService(KnowledgeBackend):
    """Shared Astra DB access helpers for search and document lifecycle actions."""

    def __init__(self, collection_name: str | None = None):
        self.collection_name = collection_name or get_index_name()
        self._database = None
        self._keyspace: str | None = None
        self._collection_cache: dict[int | None, Any] = {}

    def _require_connection_settings(self) -> tuple[str, str, str | None]:
        token = os.getenv("ASTRA_DB_APPLICATION_TOKEN")
        api_endpoint = os.getenv("ASTRA_DB_API_ENDPOINT")
        keyspace = os.getenv("ASTRA_DB_KEYSPACE") or None
        if not token or not api_endpoint:
            raise ValueError(
                "Astra DB support requires ASTRA_DB_APPLICATION_TOKEN and "
                "ASTRA_DB_API_ENDPOINT to be configured."
            )
        return token, api_endpoint, keyspace

    async def _get_database(self):
        if self._database is not None:
            return self._database, self._keyspace

        try:
            from astrapy import DataAPIClient
        except ImportError as exc:
            raise ImportError(
                "Astra DB support requires the 'astrapy' package to be installed."
            ) from exc

        token, api_endpoint, keyspace = self._require_connection_settings()
        client = DataAPIClient(token=token)
        self._database = client.get_async_database(api_endpoint, keyspace=keyspace)
        self._keyspace = keyspace
        return self._database, self._keyspace

    async def _collection_exists(self) -> bool:
        database, keyspace = await self._get_database()
        collection_names = await database.list_collection_names(keyspace=keyspace)
        return self.collection_name in collection_names

    async def _get_collection(self, embedding_dimension: int | None = None):
        cache_key = embedding_dimension
        cached = self._collection_cache.get(cache_key)
        if cached is not None:
            return cached

        database, keyspace = await self._get_database()
        if embedding_dimension is not None:
            collection_names = await database.list_collection_names(keyspace=keyspace)
            if self.collection_name not in collection_names:
                from astrapy.info import CollectionDefinition, CollectionVectorOptions

                await database.create_collection(
                    self.collection_name,
                    definition=CollectionDefinition(
                        vector=CollectionVectorOptions(
                            dimension=embedding_dimension,
                            metric="cosine",
                        )
                    ),
                    keyspace=keyspace,
                )
        collection = database.get_collection(self.collection_name)
        self._collection_cache[cache_key] = collection
        return collection

    async def has_indexed_documents(self) -> bool:
        if not await self._collection_exists():
            return False

        collection = await self._get_collection()
        document = await collection.find_one(projection={"_id": True})
        return document is not None

    @staticmethod
    def _metadata_field(field_name: str) -> str:
        return f"metadata.{field_name}"

    def _combine_clauses(self, clauses: list[dict[str, Any]]) -> dict[str, Any]:
        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    @staticmethod
    def _combine_any_clauses(clauses: list[dict[str, Any]]) -> dict[str, Any]:
        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$or": clauses}

    def _build_field_filter(self, field_name: str, values: list[str]) -> dict[str, Any]:
        metadata_field = self._metadata_field(field_name)
        if len(values) == 1:
            return {metadata_field: values[0]}
        return {metadata_field: {"$in": values}}

    def _build_filter(self, filters: Dict[str, Any] | None = None) -> dict[str, Any]:
        if not filters:
            return {}

        field_mapping = {
            "data_sources": "filename",
            "document_types": "mimetype",
            "owners": "owner",
            "connector_types": "connector_type",
        }

        clauses: list[dict[str, Any]] = []
        for filter_key, values in filters.items():
            if values is None or not isinstance(values, list):
                continue

            field_name = field_mapping.get(filter_key, filter_key)
            if len(values) == 0:
                clauses.append({self._metadata_field(field_name): "__IMPOSSIBLE_VALUE__"})
            else:
                clauses.append(self._build_field_filter(field_name, values))

        return self._combine_clauses(clauses)

    def _build_filter_set(self, filter_set: Dict[str, Any] | None = None) -> dict[str, Any]:
        if not filter_set:
            return {}

        clauses: list[dict[str, Any]] = []
        for field_name, values in filter_set.items():
            if values is None:
                continue

            if isinstance(values, list):
                if len(values) == 0:
                    clauses.append({self._metadata_field(field_name): "__IMPOSSIBLE_VALUE__"})
                else:
                    clauses.append(self._build_field_filter(field_name, values))
            else:
                clauses.append({self._metadata_field(field_name): values})

        return self._combine_clauses(clauses)

    def _build_access_filter(
        self,
        access_context: KnowledgeAccessContext | None,
    ) -> dict[str, Any]:
        if access_context is None or not access_context.enforce_acl:
            return {}

        principals = list(access_context.principals)
        groups = list(access_context.groups)
        any_visible_clauses = [{self._metadata_field("owner"): {"$exists": False}}]

        if principals:
            any_visible_clauses.append(
                self._build_field_filter("owner", principals)
            )
            any_visible_clauses.append(
                {self._metadata_field("allowed_users"): {"$in": principals}}
            )

        if groups:
            any_visible_clauses.append(
                {self._metadata_field("allowed_groups"): {"$in": groups}}
            )

        if not principals and not groups:
            return {self._metadata_field("owner"): {"$exists": False}}

        return self._combine_any_clauses(any_visible_clauses)

    def _combine_with_access_filter(
        self,
        filter_clause: dict[str, Any],
        access_context: KnowledgeAccessContext | None,
    ) -> dict[str, Any]:
        access_filter = self._build_access_filter(access_context)
        clauses = [clause for clause in [filter_clause, access_filter] if clause]
        return self._combine_clauses(clauses)

    @staticmethod
    def _extract_metadata(document: dict[str, Any]) -> dict[str, Any]:
        metadata = {}
        nested_metadata = document.get("metadata")
        if isinstance(nested_metadata, dict):
            metadata.update(nested_metadata)

        for key, value in document.items():
            if key in _RESERVED_DOCUMENT_FIELDS:
                continue
            metadata.setdefault(key, value)

        return metadata

    @staticmethod
    def _extract_text(document: dict[str, Any]) -> str:
        for key in ("content", "$vectorize", "page_content", "text"):
            value = document.get(key)
            if isinstance(value, str):
                return value
        return ""

    @staticmethod
    def _build_terms_agg(chunks: list[dict[str, Any]], field_name: str) -> dict[str, Any]:
        counts = Counter(
            value
            for chunk in chunks
            for value in [chunk.get(field_name)]
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
    def _build_aggregations(chunks: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "data_sources": AstraDBService._build_terms_agg(chunks, "filename"),
            "document_types": AstraDBService._build_terms_agg(chunks, "mimetype"),
            "owners": AstraDBService._build_terms_agg(chunks, "owner"),
            "connector_types": AstraDBService._build_terms_agg(chunks, "connector_type"),
            "embedding_models": AstraDBService._build_terms_agg(chunks, "embedding_model"),
        }

    async def index_chunks(
        self,
        chunks: list[dict[str, Any]],
        access_context: KnowledgeAccessContext | None = None,
    ) -> None:
        if not chunks:
            return

        embedding_dimension = None
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if isinstance(embedding, list) and embedding:
                embedding_dimension = len(embedding)
                break

        collection = await self._get_collection(embedding_dimension=embedding_dimension)
        for chunk in chunks:
            metadata = dict(chunk.get("metadata") or {})
            document = {
                "_id": chunk["id"],
                "content": chunk.get("text"),
                "metadata": metadata,
            }

            embedding = chunk.get("embedding")
            if embedding is not None:
                document["$vector"] = embedding

            await collection.replace_one(
                {"_id": chunk["id"]},
                document,
                upsert=True,
            )

    async def filename_exists(
        self,
        filename: str,
        access_context: KnowledgeAccessContext | None = None,
    ) -> bool:
        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return False

        collection = await self._get_collection()
        document = await collection.find_one(
            filter=self._combine_with_access_filter(
                self._build_field_filter("filename", candidate_filenames),
                access_context,
            ),
            projection={"_id": True},
        )
        return document is not None

    async def document_exists(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext | None = None,
    ) -> bool:
        if not document_id:
            return False

        collection = await self._get_collection()
        document = await collection.find_one(
            filter=self._combine_with_access_filter(
                self._build_filter_set({"document_id": document_id}),
                access_context,
            ),
            projection={"_id": True},
        )
        return document is not None

    async def delete_by_filename(
        self,
        filename: str,
        access_context: KnowledgeAccessContext | None = None,
    ) -> int:
        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            logger.info(
                "Skipped Astra DB delete_by_filename due to empty filename input",
                filename=filename,
            )
            return 0

        collection = await self._get_collection()
        result = await collection.delete_many(
            filter=self._combine_with_access_filter(
                self._build_field_filter("filename", candidate_filenames),
                access_context,
            ),
        )
        return result.deleted_count or 0

    async def delete_by_document_id(
        self,
        document_id: str,
        access_context: KnowledgeAccessContext | None = None,
    ) -> int:
        if not document_id:
            return 0

        collection = await self._get_collection()
        result = await collection.delete_many(
            filter=self._combine_with_access_filter(
                self._build_filter_set({"document_id": document_id}),
                access_context,
            ),
        )
        return result.deleted_count or 0

    async def delete_by_filter_sets(
        self,
        filter_sets: list[dict[str, Any]],
        *,
        access_context: KnowledgeAccessContext | None = None,
        match_any: bool = True,
    ) -> int:
        if not filter_sets:
            return 0

        normalized_clauses = [
            self._build_filter_set(filter_set)
            for filter_set in filter_sets
            if filter_set
        ]
        normalized_clauses = [clause for clause in normalized_clauses if clause]
        if not normalized_clauses:
            return 0

        filter_clause = (
            self._combine_any_clauses(normalized_clauses)
            if match_any
            else self._combine_clauses(normalized_clauses)
        )
        collection = await self._get_collection()
        result = await collection.delete_many(
            filter=self._combine_with_access_filter(filter_clause, access_context)
        )
        return result.deleted_count or 0

    async def list_connector_file_refs(
        self,
        connector_type: str,
        access_context: KnowledgeAccessContext | None = None,
    ) -> tuple[list[str], list[str]]:
        if not connector_type:
            return [], []

        collection = await self._get_collection()
        cursor = collection.find(
            filter=self._combine_with_access_filter(
                self._build_filter_set({"connector_type": connector_type}),
                access_context,
            ),
            projection={"metadata": True},
            limit=10000,
        )
        raw_documents = await cursor.to_list()
        document_ids = []
        filenames = []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue
            metadata = self._extract_metadata(document)
            document_id = metadata.get("document_id")
            filename = metadata.get("filename")
            if isinstance(document_id, str) and document_id and document_id not in document_ids:
                document_ids.append(document_id)
            if isinstance(filename, str) and filename and filename not in filenames:
                filenames.append(filename)
        return document_ids, filenames

    async def refresh(self) -> None:
        return None

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
        collection = await self._get_collection()
        is_wildcard_match_all = isinstance(query, str) and query.strip() in {"", "*"}
        embedding_vector = None
        if not is_wildcard_match_all:
            resolved_embedding_model = (
                embedding_model or get_embedding_model() or OPENAI_DEFAULT_EMBEDDING_MODEL
            )
            embedding_vector = await embed_query(query, resolved_embedding_model)

        filter_clause = self._combine_with_access_filter(
            self._build_filter(filters),
            access_context,
        )
        find_kwargs: dict[str, Any] = {
            "filter": filter_clause or None,
            "projection": {
                "_id": True,
                "content": True,
                "$vectorize": True,
                "metadata": True,
            },
            "limit": max(limit, 1),
        }

        if is_wildcard_match_all:
            cursor = collection.find(**find_kwargs)
        else:
            if embedding_vector is None:
                raise ValueError("An embedding vector is required for Astra DB search.")
            cursor = collection.find(
                **find_kwargs,
                sort={"$vector": embedding_vector},
                include_similarity=True,
            )

        raw_documents = await cursor.to_list()
        chunks: list[dict[str, Any]] = []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue

            metadata = self._extract_metadata(document)
            score = document.get("$similarity")
            if (
                not is_wildcard_match_all
                and score_threshold > 0
                and isinstance(score, (int, float))
                and score < score_threshold
            ):
                continue

            chunks.append(
                {
                    "filename": metadata.get("filename"),
                    "mimetype": metadata.get("mimetype"),
                    "page": metadata.get("page"),
                    "text": self._extract_text(document),
                    "score": score,
                    "source_url": metadata.get("source_url"),
                    "owner": metadata.get("owner"),
                    "owner_name": metadata.get("owner_name"),
                    "owner_email": metadata.get("owner_email"),
                    "file_size": metadata.get("file_size"),
                    "connector_type": metadata.get("connector_type"),
                    "embedding_model": metadata.get("embedding_model"),
                    "embedding_dimensions": metadata.get("embedding_dimensions"),
                    "allowed_users": metadata.get("allowed_users", []),
                    "allowed_groups": metadata.get("allowed_groups", []),
                }
            )

        normalized_query = query.strip().lower()
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
                chunks = [
                    chunk for chunk in chunks if chunk.get("filename") in exact_files
                ]

        return {
            "results": chunks,
            "aggregations": self._build_aggregations(chunks),
            "total": len(chunks),
        }
