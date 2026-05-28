"""Shared backend-owned OpenSearch document indexing.

Langflow can generate chunks and embeddings, but it must not hold credentials
that can write arbitrary documents. This writer is the single backend path for
indexing chunks into the documents index.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from typing import Any

from utils.embedding_fields import ensure_embedding_field_exists
from utils.embeddings import create_index_body
from utils.group_acl import unique_acl_principal_labels, unique_acl_principals
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class DocumentIndexContext:
    document_id: str
    filename: str
    mimetype: str
    embedding_model: str
    owner: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    file_size: int | None = None
    connector_type: str | None = None
    source_url: str | None = None
    allowed_users: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)
    allowed_principals: list[str] = field(default_factory=list)
    allowed_principal_labels: list[dict[str, Any]] = field(default_factory=list)
    ingest_run_id: str | None = None
    is_sample_data: bool = False
    index_name: str | None = None


@dataclass
class DocumentIndexChunk:
    chunk_id: str
    text: str
    vector: list[float]
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentIndexWriter:
    """Write document chunks with a trusted backend OpenSearch client."""

    def __init__(self, opensearch_client: Any | None = None):
        self.opensearch_client = opensearch_client

    def _get_write_client(self) -> Any:
        from config.settings import clients

        client = self.opensearch_client or clients.opensearch
        if client is None:
            raise RuntimeError(
                "Backend OpenSearch write client is unavailable; cannot index document chunks"
            )
        return client

    async def index_chunks(
        self,
        context: DocumentIndexContext,
        chunks: list[DocumentIndexChunk],
        *,
        final: bool = False,
        refresh: bool | str = False,
    ) -> dict[str, Any]:
        """Index one batch of chunks.

        Repeated calls with the same chunk ids are idempotent because the write
        operation is an index/upsert.
        """
        from config.settings import get_index_name

        if not chunks:
            if final:
                await self._refresh(context.index_name or get_index_name())
            return {"indexed_chunks": 0, "ingest_run_id": context.ingest_run_id}

        first_vector = chunks[0].vector
        if not first_vector:
            raise ValueError("Cannot index chunks with empty embeddings")

        dimensions = len(first_vector)
        client = self._get_write_client()
        index_name = context.index_name or get_index_name()
        embedding_field = await self._ensure_index_and_embedding_field(
            client,
            index_name=index_name,
            embedding_model=context.embedding_model,
            dimensions=dimensions,
        )

        now = datetime.datetime.now(datetime.UTC).isoformat()
        bulk_body: list[dict[str, Any]] = []
        for chunk in chunks:
            if len(chunk.vector) != dimensions:
                raise ValueError(
                    "Embedding dimension mismatch in batch: "
                    f"expected {dimensions}, got {len(chunk.vector)} for {chunk.chunk_id}"
                )
            bulk_body.append({"index": {"_index": index_name, "_id": chunk.chunk_id}})
            bulk_body.append(
                self._build_chunk_document(
                    context=context,
                    chunk=chunk,
                    embedding_field=embedding_field,
                    indexed_time=now,
                )
            )

        result = await client.bulk(body=bulk_body, refresh=refresh)
        self._raise_for_bulk_errors(result)
        if final:
            await self._refresh(index_name)

        logger.info(
            "Indexed document chunks",
            index_name=index_name,
            document_id=context.document_id,
            ingest_run_id=context.ingest_run_id,
            chunk_count=len(chunks),
            final=final,
        )
        return {
            "indexed_chunks": len(chunks),
            "ingest_run_id": context.ingest_run_id,
            "document_id": context.document_id,
        }

    async def delete_ingest_run(self, ingest_run_id: str, *, index_name: str | None = None) -> int:
        """Delete partially indexed chunks for a failed callback run."""
        if not ingest_run_id:
            return 0
        from config.settings import get_index_name

        client = self._get_write_client()
        resolved_index = index_name or get_index_name()
        body = {"query": {"term": {"ingest_run_id": ingest_run_id}}}
        response = await client.delete_by_query(
            index=resolved_index,
            body=body,
            refresh=True,
            conflicts="proceed",
        )
        deleted = int(response.get("deleted", 0)) if isinstance(response, dict) else 0
        logger.info(
            "Deleted failed ingest run chunks",
            index_name=resolved_index,
            ingest_run_id=ingest_run_id,
            deleted=deleted,
        )
        return deleted

    async def _ensure_index_and_embedding_field(
        self,
        client: Any,
        *,
        index_name: str,
        embedding_model: str,
        dimensions: int,
    ) -> str:
        if not await client.indices.exists(index=index_name):
            await client.indices.create(
                index=index_name,
                body=await create_index_body(embedding_model, dimensions),
            )
        return await ensure_embedding_field_exists(
            client,
            embedding_model,
            index_name,
            dimensions,
        )

    def _build_chunk_document(
        self,
        *,
        context: DocumentIndexContext,
        chunk: DocumentIndexChunk,
        embedding_field: str,
        indexed_time: str,
    ) -> dict[str, Any]:
        metadata = self._normalized_metadata(chunk.metadata)
        document_id = context.document_id or str(metadata.get("document_id") or chunk.chunk_id)
        filename = context.filename or str(metadata.get("filename") or "")
        mimetype = context.mimetype or str(metadata.get("mimetype") or "")

        doc: dict[str, Any] = {
            "document_id": document_id,
            "filename": filename,
            "mimetype": mimetype,
            "page": chunk.page if chunk.page is not None else metadata.get("page", 0),
            "text": chunk.text,
            embedding_field: chunk.vector,
            "embedding_model": context.embedding_model,
            "embedding_dimensions": len(chunk.vector),
            "file_size": context.file_size
            if context.file_size is not None
            else metadata.get("file_size"),
            "connector_type": context.connector_type or metadata.get("connector_type") or "local",
            "source_url": context.source_url or metadata.get("source_url") or "",
            "owner": context.owner,
            "allowed_users": list(context.allowed_users),
            "allowed_groups": list(context.allowed_groups),
            "allowed_principals": unique_acl_principals(context.allowed_principals),
            "allowed_principal_labels": unique_acl_principal_labels(
                context.allowed_principal_labels
            ),
            "indexed_time": indexed_time,
            "metadata": metadata.get("metadata", {}),
        }

        if context.owner_name is not None:
            doc["owner_name"] = context.owner_name
        if context.owner_email is not None:
            doc["owner_email"] = context.owner_email
        if context.ingest_run_id:
            doc["ingest_run_id"] = context.ingest_run_id
        if metadata.get("connector_file_id"):
            doc["connector_file_id"] = metadata["connector_file_id"]
        if context.is_sample_data:
            doc["is_sample_data"] = "true"
        for time_field in ("created_time", "modified_time"):
            if metadata.get(time_field):
                doc[time_field] = metadata[time_field]

        return doc

    @staticmethod
    def _normalized_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(metadata or {})
        for key in (
            "allowed_users",
            "allowed_groups",
            "allowed_principals",
            "allowed_principal_labels",
        ):
            value = normalized.get(key)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, list):
                    normalized[key] = parsed
        if "filesize" in normalized and "file_size" not in normalized:
            normalized["file_size"] = normalized["filesize"]
        return normalized

    @staticmethod
    def _raise_for_bulk_errors(result: Any) -> None:
        if not isinstance(result, dict) or not result.get("errors"):
            return
        failures = []
        for item in result.get("items", [])[:5]:
            action = item.get("index") or item.get("create") or item.get("update") or item
            failures.append(
                {
                    "id": action.get("_id"),
                    "status": action.get("status"),
                    "error": action.get("error"),
                }
            )
        raise RuntimeError(f"OpenSearch bulk indexing failed: {failures}")

    async def _refresh(self, index_name: str) -> None:
        client = self._get_write_client()
        await client.indices.refresh(index=index_name)
