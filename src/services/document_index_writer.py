"""Shared backend-owned OpenSearch document indexing.

Langflow can generate chunks and embeddings, but it must not hold credentials
that can write arbitrary documents. This writer is the single backend path for
indexing chunks into the documents index.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from utils.embedding_fields import ensure_embedding_field_exists, get_embedding_space_id
from utils.embeddings import create_index_body
from utils.group_acl import unique_acl_principal_labels, unique_acl_principals
from utils.logging_config import get_logger

logger = get_logger(__name__)

# A bulk() call executes every item independently. Thus, if one item hits a
# transient condition (cluster under load, shard unavailable) the whole response
# gets errors: true even though the rest of the document chunks wrote
# successfully. This makes the entire file look like it "failed" in task
# counters even when it's actually indexed and visible. But every op is an
# idempotent upsert so retries are safe — only the items still failing are
# resent, not the whole body.
_BULK_RETRYABLE_ERROR_TYPES = frozenset(
    {
        "es_rejected_execution_exception",
        "process_cluster_event_timeout_exception",
        "unavailable_shards_exception",
        "timeout_exception",
        # version_conflicts are intentionally excluded — they result from
        # concurrent writes to the same document ID, not transient failures.
        # Retrying would just hit the same conflict again and waste the budget.
    }
)
_MAX_BULK_RETRIES = 2
_BULK_RETRY_DELAY_SECONDS = 0.5


@dataclass
class DocumentIndexContext:
    document_id: str
    mimetype: str
    embedding_model: str
    embedding_provider: str | None = None
    filename: str | None = None
    owner: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    file_size: int | None = None
    connector_type: str | None = None
    source_url: str | None = None
    connector_file_id: str | None = None
    allowed_users: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)
    allowed_principals: list[str] = field(default_factory=list)
    allowed_principal_labels: list[dict[str, Any]] = field(default_factory=list)
    ingest_run_id: str | None = None
    is_sample_data: bool = False
    index_name: str | None = None
    parser: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    record_kind: str | None = None
    web_source_id: str | None = None
    web_page_id: str | None = None
    web_page_depth: int | None = None
    root_source_url: str | None = None
    canonical_url: str | None = None


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

        Repeated calls with the same chunk ids in the same ownership scope are
        idempotent because the write operation is an index/upsert.
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
        embedding_space_id = self._embedding_space_id(context)
        client = self._get_write_client()
        index_name = context.index_name or get_index_name()
        embedding_field = await self._ensure_index_and_embedding_field(
            client,
            index_name=index_name,
            embedding_model=context.embedding_model,
            embedding_provider=context.embedding_provider,
            embedding_space_id=embedding_space_id,
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
            bulk_body.append(
                {
                    "index": {
                        "_index": index_name,
                        "_id": self._scoped_chunk_id(context, chunk.chunk_id),
                    }
                }
            )
            bulk_body.append(
                self._build_chunk_document(
                    context=context,
                    chunk=chunk,
                    embedding_field=embedding_field,
                    indexed_time=now,
                )
            )

        result = await self._bulk_with_retry(client, bulk_body, refresh=refresh)
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

    @staticmethod
    def _scoped_chunk_id(context: DocumentIndexContext, chunk_id: str) -> str:
        """Keep idempotent chunk upserts isolated to one ownership scope."""
        scope = "shared" if context.owner is None else f"owner:{context.owner}"
        scope_digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
        return f"{scope_digest}_{chunk_id}"

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
        embedding_provider: str | None,
        embedding_space_id: str,
        dimensions: int,
    ) -> str:
        if not await client.indices.exists(index=index_name):
            await client.indices.create(
                index=index_name,
                body=await create_index_body(
                    embedding_model,
                    dimensions,
                    embedding_provider=embedding_provider,
                    embedding_space_id=embedding_space_id,
                ),
            )
        return await ensure_embedding_field_exists(
            client,
            embedding_space_id,
            index_name,
            dimensions,
        )

    @staticmethod
    def _embedding_space_id(context: DocumentIndexContext) -> str:
        """Use exact provider provenance when present; preserve legacy ids otherwise."""
        if context.embedding_provider:
            return get_embedding_space_id(context.embedding_provider, context.embedding_model)
        return context.embedding_model

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
            "allowed_users": list(context.allowed_users),
            "allowed_groups": list(context.allowed_groups),
            "allowed_principals": unique_acl_principals(context.allowed_principals),
            "allowed_principal_labels": unique_acl_principal_labels(
                context.allowed_principal_labels
            ),
            "indexed_time": indexed_time,
            "metadata": metadata.get("metadata", {}),
        }

        if context.embedding_provider:
            doc["embedding_provider"] = context.embedding_provider.strip().lower()
            doc["embedding_space_id"] = self._embedding_space_id(context)

        parser = context.parser or metadata.get("parser")
        if parser:
            doc["parser"] = parser

        for field_name in ("chunk_size", "chunk_overlap"):
            context_value = getattr(context, field_name)
            value = context_value if context_value is not None else metadata.get(field_name)
            if value is None:
                continue
            try:
                doc[field_name] = int(value)
            except (TypeError, ValueError):
                # Skip assignment if coercion fails to avoid type conflicts
                pass

        if context.owner is not None:
            doc["owner"] = context.owner
        if context.owner_name is not None:
            doc["owner_name"] = context.owner_name
        if context.owner_email is not None:
            doc["owner_email"] = context.owner_email
        if context.ingest_run_id:
            doc["ingest_run_id"] = context.ingest_run_id
        if context.connector_file_id:
            doc["connector_file_id"] = context.connector_file_id
        elif metadata.get("connector_file_id"):
            doc["connector_file_id"] = metadata["connector_file_id"]
        if context.is_sample_data:
            doc["is_sample_data"] = "true"
        for field_name in (
            "record_kind",
            "web_source_id",
            "web_page_id",
            "web_page_depth",
            "root_source_url",
            "canonical_url",
        ):
            value = getattr(context, field_name)
            if value is not None:
                doc[field_name] = value
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
    def _item_error(item: Any) -> dict[str, Any] | None:
        action = item.get("index") or item.get("create") or item.get("update") or item
        return action.get("error")

    @classmethod
    def _item_error_is_retryable(cls, item: Any) -> bool:
        error = cls._item_error(item)
        # When there is no error the item succeeded — we treat it as retryable
        # so a successful item never blocks a retry when this runs over the
        # still_pending list (which only ever holds items that actually failed).
        return not error or error.get("type") in _BULK_RETRYABLE_ERROR_TYPES

    async def _bulk_with_retry(
        self, client: Any, bulk_body: list[dict[str, Any]], *, refresh: bool | str
    ) -> Any:
        """Only retry the items that actually failed, not the whole bulk body.

        Each entry in the bulk response lines up by position with the
        action/document pairs we sent. If we resend everything on retry we
        end up re-submitting pairs that already succeeded — and under heavy
        load a different subset can fail each time, meaning the file still
        gets marked failed even though every pair succeeded at some point.
        Instead we track each pair by its original position and only rebuild
        the retry body from the ones still failing.
        """
        if len(bulk_body) % 2 != 0:
            raise ValueError(
                f"bulk_body must contain action/document pairs; got {len(bulk_body)} elements"
            )
        pairs = [tuple(bulk_body[i : i + 2]) for i in range(0, len(bulk_body), 2)]
        pending_indices = list(range(len(pairs)))
        final_items: list[Any] = [None] * len(pairs)

        for attempt in range(_MAX_BULK_RETRIES + 1):
            retry_body = [part for i in pending_indices for part in pairs[i]]
            result = await client.bulk(body=retry_body, refresh=refresh)
            if not isinstance(result, dict):
                return result

            items = result.get("items", [])

            # Guard against a bad or cut-short response — the server should
            # return exactly one item for each request we sent. If the list
            # is short or empty we can't safely match results back to the
            # right slots, so we treat it as an error rather than leaving
            # gaps filled with None.
            if len(items) != len(pending_indices):
                raise RuntimeError(
                    f"OpenSearch bulk response returned {len(items)} items for "
                    f"{len(pending_indices)} requests — malformed response"
                )

            still_pending = []
            for original_index, item in zip(pending_indices, items, strict=True):
                final_items[original_index] = item
                if self._item_error(item):
                    still_pending.append(original_index)

            if not still_pending:
                # Keep the top-level error flag as-is — if the server
                # said errors: true but none of the individual items show
                # an error, we still want to surface that rather than
                # quietly calling it a success.
                return {**result, "items": final_items, "errors": result.get("errors", False)}

            all_retryable = all(
                self._item_error_is_retryable(final_items[i]) for i in still_pending
            )
            if not all_retryable or attempt == _MAX_BULK_RETRIES:
                return {**result, "items": final_items, "errors": True}

            logger.warning(
                "Retrying OpenSearch bulk write after transient error",
                attempt=attempt + 1,
                remaining_items=len(still_pending),
            )
            await asyncio.sleep(_BULK_RETRY_DELAY_SECONDS * (attempt + 1))
            pending_indices = still_pending

        return {"items": final_items, "errors": True}

    @staticmethod
    def _raise_for_bulk_errors(result: Any) -> None:
        if not isinstance(result, dict) or not result.get("errors"):
            return
        # Keep only the items that actually failed (a bulk response interleaves
        # successes and failures) and carry their full OpenSearch error body so
        # the cause — e.g. a mapper_parsing_exception naming the offending field
        # — survives in the raised error. The caller logs this once with request
        # context; this helper only raises so the failure isn't logged twice.
        failures = []
        for item in result.get("items", []):
            action = item.get("index") or item.get("create") or item.get("update") or item
            if not action.get("error"):
                continue
            failures.append(
                {
                    "id": action.get("_id"),
                    "status": action.get("status"),
                    "error": action.get("error"),
                }
            )
            if len(failures) >= 5:
                break
        if not failures:
            # `errors` was set but no item carried an error body (rare/contradictory);
            # fall back to the first few raw items so the message keeps some detail.
            failures = result.get("items", [])[:3]
        raise RuntimeError(f"OpenSearch bulk indexing failed: {failures}")

    async def _refresh(self, index_name: str) -> None:
        client = self._get_write_client()
        await client.indices.refresh(index=index_name)
