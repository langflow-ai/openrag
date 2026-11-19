"""Search imported OpenSearch datasets with the caller's own OpenSearch identity.

Each dataset is one alias the restore created. It is searched with the user's
client, so OpenSearch security (the per-import role mapping) is what grants or
denies access; a 403 on one dataset only removes that dataset from the answer.
Retrieval identity is always the auth-context user (``get_auth_context``), never
the conversation storage id.

The lookup of which datasets a user can see lives in
``connectors.opensearch_snapshot.service``; it is imported lazily because that
module only exists with the connector and importing it eagerly would couple
document search to it.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from auth_context import get_auth_context
from observability.spans import trace_span
from services import llm_gateway
from utils.dataset_selection import effective_ids
from utils.logging_config import get_logger

if TYPE_CHECKING:
    from connectors.opensearch_snapshot.service import DatasetRecord

logger = get_logger(__name__)

DATASET_MIMETYPE = "application/x-opensearch-document"
DATASET_CONNECTOR_TYPE = "opensearch_snapshot"
MAX_TEXT_CHARS = 4_000
TITLE_BOOST = 1.5
RRF_K = 60

# Error codes reported per dataset (never raw exception text).
ERR_FORBIDDEN = "forbidden"
ERR_NOT_FOUND = "not_found"
ERR_TIMEOUT = "timeout"
ERR_SEARCH_FAILED = "search_failed"
ERR_BAD_FIELD_MAP = "invalid_field_map"
ERR_EMBEDDING_FAILED = "embedding_failed"
ERR_EMBEDDING_DIMS = "embedding_dims_mismatch"
ERR_BAD_RETRIEVAL = "invalid_retrieval"


# ----------------------------------------------------------------------
# Feature + visibility seams (lazy: the connector may not be installed)
# ----------------------------------------------------------------------


def snapshot_import_available() -> bool:
    """Whether dataset retrieval is switched on for this deployment."""
    from config.settings import is_snapshot_import_available

    available, _reason = is_snapshot_import_available()
    return bool(available)


async def list_visible_datasets(user_id: str) -> list[DatasetRecord]:
    """Active datasets the user owns or that are shared with them."""
    from connectors.opensearch_snapshot.service import list_searchable_datasets

    return await list_searchable_datasets(user_id)


async def resolve_datasets(
    selection: list[str] | None, tool_requested: list[str] | None = None
) -> list[DatasetRecord]:
    """The datasets this request may search: ``visible ∩ selection ∩ tool_requested``.

    Identity comes from the auth context, which is what the OpenSearch client is
    built from, so what is listed is what OpenSearch will actually authorise.
    Returns ``[]`` without touching the registry when the feature is off, when
    there is no authenticated user, or when the selection is empty.
    """
    if selection is not None and not selection:
        return []
    if not snapshot_import_available():
        return []
    user_id, _jwt = get_auth_context()
    if not user_id:
        return []
    visible = await list_visible_datasets(user_id)
    if tool_requested is not None:
        # Models often pass the dataset names they were shown instead of ids;
        # map those to ids so the tool narrows rather than silently matching nothing.
        by_name: dict[str, str] = {}
        for record in visible:
            for name in (record.display_name, record.source_index):
                if name:
                    by_name.setdefault(name.strip().lower(), record.id)
        tool_requested = [by_name.get(str(item).strip().lower(), item) for item in tool_requested]
    keep = set(effective_ids(selection, [record.id for record in visible], tool_requested))
    return [record for record in visible if record.id in keep]


# ----------------------------------------------------------------------
# Result shaping
# ----------------------------------------------------------------------


def _chunk_id(dataset_id: str, doc_id: str) -> str:
    encoded = base64.urlsafe_b64encode(doc_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ds-{dataset_id}-{encoded}"


def _field_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _source_value(source: dict[str, Any], path: str) -> Any:
    """Value at a dotted ``_source`` path; a literal dotted key wins over nesting."""
    if path in source:
        return source[path]
    nodes: list[Any] = [source]
    for part in path.split("."):
        found: list[Any] = []
        for node in nodes:
            # Arrays of objects are traversed without consuming a path component.
            for item in node if isinstance(node, list) else [node]:
                if isinstance(item, dict) and part in item:
                    found.append(item[part])
        if not found:
            return None
        nodes = found
    return nodes[0] if len(nodes) == 1 else nodes


def _nested_paths(record: DatasetRecord) -> list[str]:
    """Paths of ``nested`` mappings recorded for the dataset (v1 does not query them)."""
    mapping = record.field_map if isinstance(record.field_map, dict) else {}
    return _field_list(mapping.get("nested_paths"))


def _under_nested(field: str, nested: list[str]) -> bool:
    return any(field == path or field.startswith(path + ".") for path in nested)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return " ".join(part for part in (_as_text(item) for item in value) if part)
    if isinstance(value, dict):
        return ""
    return str(value)


def _field_map(record: DatasetRecord) -> tuple[list[str], str | None, str | None]:
    mapping = record.field_map if isinstance(record.field_map, dict) else {}
    text_fields = _field_list(mapping.get("text_fields"))
    title = mapping.get("title_field")
    url = mapping.get("url_field")
    return (
        text_fields,
        title if isinstance(title, str) and title else None,
        url if isinstance(url, str) and url else None,
    )


def _build_hit(record: DatasetRecord, hit: dict[str, Any]) -> dict[str, Any]:
    text_fields, title_field, url_field = _field_map(record)
    doc_id = str(hit.get("_id", ""))
    source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
    text = " ".join(
        part for part in (_as_text(_source_value(source, f)) for f in text_fields) if part
    )[:MAX_TEXT_CHARS]
    title = _as_text(_source_value(source, title_field)) if title_field else ""
    url = _as_text(_source_value(source, url_field)) if url_field else ""
    highlights: list[str] = []
    for fragments in (hit.get("highlight") or {}).values():
        if isinstance(fragments, list):
            highlights.extend(fragment for fragment in fragments if isinstance(fragment, str))
    chunk_id = _chunk_id(record.id, doc_id)
    return {
        "chunk_id": chunk_id,
        "id": chunk_id,
        "text": text,
        "filename": f"{record.display_name} / {title or doc_id}",
        "source_url": url or f"opensearch://{record.index_alias}/{doc_id}",
        "score": hit.get("_score"),
        "highlights": highlights,
        "page": None,
        "mimetype": DATASET_MIMETYPE,
        "connector_type": DATASET_CONNECTOR_TYPE,
        "document_id": f"{record.index_alias}/{doc_id}",
        "dataset": {
            "id": record.id,
            "name": record.display_name,
            "import_name": record.import_name,
            "source_index": record.source_index,
        },
    }


def rrf_merge(
    lists: Iterable[list[dict[str, Any]]], *, k: int = RRF_K, limit: int
) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion of ranked result lists, keyed by ``chunk_id``.

    The merged ``score`` is the fusion score: raw scores from different indices
    are not comparable, so they are not used. Inputs are not mutated.
    """
    fused: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for ranked in lists:
        for rank, item in enumerate(ranked, start=1):
            key = item.get("chunk_id") or item.get("id")
            if key is None:
                key = f"{item.get('filename')}\x00{item.get('text')}"
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
            items.setdefault(key, item)
    order = sorted(fused, key=lambda key: fused[key], reverse=True)
    return [{**items[key], "score": fused[key]} for key in order[: max(limit, 0)]]


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return ERR_TIMEOUT
    status = getattr(exc, "status_code", None)
    if status == 403:
        return ERR_FORBIDDEN
    if status == 404:
        return ERR_NOT_FOUND
    return ERR_SEARCH_FAILED


class DatasetSearchService:
    """Lexical (+ optional kNN) search over imported dataset aliases."""

    def __init__(self, session_manager: Any) -> None:
        self.session_manager = session_manager

    async def search(
        self,
        query: str,
        *,
        user_id: str,
        jwt_token: str | None,
        dataset_ids: list[str],
        limit: int = 5,
        timeout_s: float = 8.0,
    ) -> dict[str, Any]:
        """Search ``dataset_ids`` (those the user can see) and merge by RRF.

        Returns ``{"results": [...], "errors": [{"dataset_id", "code"}]}``. One
        dataset failing, including a 403 from OpenSearch, never fails the rest.
        """
        errors: list[dict[str, Any]] = []
        if not dataset_ids or not (query or "").strip() or limit <= 0:
            return {"results": [], "errors": errors}

        visible = {record.id: record for record in await list_visible_datasets(user_id)}
        records = [visible[i] for i in dict.fromkeys(dataset_ids) if i in visible]
        if not records:
            return {"results": [], "errors": errors}

        client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
        vectors = await self._embed_for_hybrid(query, records, timeout_s)

        outcomes = await asyncio.gather(
            *(
                self._search_dataset(client, record, query, limit, vectors, timeout_s)
                for record in records
            )
        )
        ranked: list[list[dict[str, Any]]] = []
        for record, (hits, codes) in zip(records, outcomes, strict=True):
            ranked.append(hits)
            errors.extend({"dataset_id": record.id, "code": code} for code in codes)
        return {"results": rrf_merge(ranked, limit=limit), "errors": errors}

    @staticmethod
    def _retrieval(record: DatasetRecord) -> dict[str, Any]:
        return record.retrieval if isinstance(record.retrieval, dict) else {}

    async def _embed_for_hybrid(
        self, query: str, records: list[DatasetRecord], timeout_s: float
    ) -> dict[str, list[float] | str]:
        """Query vector per qualified model, or an error code string on failure."""
        models: dict[str, None] = {}
        for record in records:
            retrieval = self._retrieval(record)
            if retrieval.get("mode") == "hybrid" and retrieval.get("model"):
                models[self._model_id(retrieval)] = None

        async def embed(model_id: str) -> list[float]:
            response = await llm_gateway.embeddings(
                {"model": model_id, "input": [query]}, interactive=True
            )
            data = response.get("data") or []
            vector = data[0].get("embedding") if data else None
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("embedding provider returned no vector")
            return vector

        async def guarded(model_id: str) -> tuple[str, list[float] | str]:
            try:
                return model_id, await asyncio.wait_for(embed(model_id), timeout_s)
            except Exception as exc:
                logger.warning(
                    "Dataset query embedding failed",
                    model=model_id,
                    error_type=type(exc).__name__,
                )
                return model_id, ERR_EMBEDDING_FAILED

        return dict(await asyncio.gather(*(guarded(model_id) for model_id in models)))

    @staticmethod
    def _model_id(retrieval: dict[str, Any]) -> str:
        return llm_gateway.qualified_model_id(retrieval.get("provider"), str(retrieval["model"]))

    def _build_body(
        self,
        record: DatasetRecord,
        query: str,
        limit: int,
        vectors: dict[str, list[float] | str],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """The request body for one dataset, plus error codes that do not stop it."""
        text_fields, title_field, url_field = _field_map(record)
        nested = _nested_paths(record)
        text_fields = [f for f in text_fields if not _under_nested(f, nested)]
        if title_field and _under_nested(title_field, nested):
            title_field = None
        if url_field and _under_nested(url_field, nested):
            url_field = None
        if not text_fields:
            return None, [ERR_BAD_FIELD_MAP]
        codes: list[str] = []
        fields = [*text_fields, f"{title_field}^{TITLE_BOOST}"] if title_field else text_fields
        lexical: dict[str, Any] = {
            "multi_match": {"query": query, "fields": fields, "type": "best_fields"}
        }
        clause: dict[str, Any] = lexical

        retrieval = self._retrieval(record)
        if retrieval.get("mode") == "hybrid":
            vector_field = retrieval.get("vector_field")
            vector = vectors.get(self._model_id(retrieval)) if retrieval.get("model") else None
            if (
                not vector_field
                or not retrieval.get("model")
                or _under_nested(vector_field, nested)
            ):
                codes.append(ERR_BAD_RETRIEVAL)
            elif isinstance(vector, str):
                codes.append(vector)
            elif vector is None:
                codes.append(ERR_EMBEDDING_FAILED)
            elif len(vector) != retrieval.get("dims"):
                codes.append(ERR_EMBEDDING_DIMS)
            else:
                clause = {
                    "bool": {
                        "should": [
                            lexical,
                            {"knn": {vector_field: {"vector": vector, "k": limit}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }

        source_fields = [*text_fields, *(f for f in (title_field, url_field) if f)]
        body: dict[str, Any] = {
            "size": limit,
            "query": clause,
            "_source": {"includes": source_fields},
            "highlight": {
                "fields": {
                    field: {"fragment_size": 200, "number_of_fragments": 3} for field in text_fields
                },
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "require_field_match": False,
            },
        }
        return body, codes

    async def _search_dataset(
        self,
        client: Any,
        record: DatasetRecord,
        query: str,
        limit: int,
        vectors: dict[str, list[float] | str],
        timeout_s: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        started = time.perf_counter()
        with trace_span("search.dataset", dataset_id=record.id) as span:
            body, codes = self._build_body(record, query, limit, vectors)
            if body is None:
                span.set(hits=0, error_code=codes[0] if codes else None)
                return [], codes
            try:
                response = await asyncio.wait_for(
                    client.search(index=record.index_alias, body=body), timeout_s
                )
            except Exception as exc:
                code = _error_code(exc)
                logger.warning(
                    "Dataset search failed",
                    dataset_id=record.id,
                    error_code=code,
                    error_type=type(exc).__name__,
                )
                span.set(
                    hits=0,
                    error_code=code,
                    latency_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                return [], [*codes, code]
            raw_hits = (response.get("hits") or {}).get("hits") or []
            hits = [_build_hit(record, hit) for hit in raw_hits if isinstance(hit, dict)]
            span.set(
                hits=len(hits),
                error_code=codes[0] if codes else None,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return hits, codes


def get_dataset_search_service() -> DatasetSearchService:
    """Service bound to the session manager of the registered ``SearchService``."""
    from services import search_service

    registered = search_service._global_search_service
    if registered is None:
        raise RuntimeError("SearchService is not registered")
    return DatasetSearchService(registered.session_manager)
