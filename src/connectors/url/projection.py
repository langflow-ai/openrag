"""OpenSearch manifests for managed website sources and their pages."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from config.settings import clients, get_index_name

SOURCE_MANIFEST_KIND = "web_source"
PAGE_MANIFEST_KIND = "web_page_manifest"


def source_manifest_id(source_id: str) -> str:
    return f"web-source:{source_id}"


def page_manifest_id(source_id: str, page_id: str) -> str:
    return f"web-page:{source_id}:{page_id}"


def _exact(field: str, value: str) -> dict[str, Any]:
    return {
        "bool": {
            "should": [{"term": {field: value}}, {"term": {f"{field}.keyword": value}}],
            "minimum_should_match": 1,
        }
    }


async def _get(document_id: str) -> dict[str, Any] | None:
    if clients.opensearch is None:
        return None
    try:
        result = await clients.opensearch.get(index=get_index_name(), id=document_id)
    except Exception:
        return None
    source = result.get("_source")
    return dict(source) if isinstance(source, dict) else None


async def get_source_manifest(source_id: str) -> dict[str, Any] | None:
    source = await _get(source_manifest_id(source_id))
    if source is None or source.get("record_kind") != SOURCE_MANIFEST_KIND:
        return None
    return source


async def list_source_manifests(owner_id: str) -> list[dict[str, Any]]:
    if clients.opensearch is None:
        return []
    result = await clients.opensearch.search(
        index=get_index_name(),
        body={
            "size": 10_000,
            "query": {
                "bool": {
                    "filter": [
                        _exact("record_kind", SOURCE_MANIFEST_KIND),
                        _exact("owner", owner_id),
                    ]
                }
            },
            "sort": [{"indexed_time": {"order": "desc"}}],
        },
    )
    return [
        dict(hit["_source"])
        for hit in result.get("hits", {}).get("hits", [])
        if isinstance(hit.get("_source"), dict)
    ]


async def get_page_manifest(source_id: str, page_id: str) -> dict[str, Any] | None:
    page = await _get(page_manifest_id(source_id, page_id))
    if page is None or page.get("record_kind") != PAGE_MANIFEST_KIND:
        return None
    return page


async def get_page_index_metadata(document_id: str) -> dict[str, Any]:
    """Read the embedding provenance written on one concrete page chunk."""
    if clients.opensearch is None:
        return {}
    try:
        result = await clients.opensearch.search(
            index=get_index_name(),
            body={
                "size": 1,
                "query": {"term": {"document_id": document_id}},
                "_source": [
                    "embedding_model",
                    "embedding_provider",
                    "embedding_space_id",
                    "embedding_dimensions",
                ],
            },
        )
    except Exception:
        return {}
    hits = result.get("hits", {}).get("hits", [])
    source = hits[0].get("_source", {}) if hits else {}
    return dict(source) if isinstance(source, dict) else {}


async def list_page_manifests(source_id: str, query: str = "") -> list[dict[str, Any]]:
    if clients.opensearch is None:
        return []
    filters: list[dict[str, Any]] = [
        _exact("record_kind", PAGE_MANIFEST_KIND),
        _exact("web_source_id", source_id),
    ]
    must: list[dict[str, Any]] = []
    if query.strip() and query.strip() != "*":
        value = query.strip().lower()
        must.append(
            {
                "bool": {
                    "should": [
                        {
                            "wildcard": {
                                "filename": {"value": f"*{value}*", "case_insensitive": True}
                            }
                        },
                        {
                            "wildcard": {
                                "source_url": {"value": f"*{value}*", "case_insensitive": True}
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    result = await clients.opensearch.search(
        index=get_index_name(),
        body={
            "size": 10_000,
            "query": {"bool": {"filter": filters, "must": must}},
            "sort": [{"source_url": {"order": "asc"}}],
        },
    )
    return [
        dict(hit["_source"])
        for hit in result.get("hits", {}).get("hits", [])
        if isinstance(hit.get("_source"), dict)
    ]


async def upsert_page_manifest(page: dict[str, Any]) -> None:
    if clients.opensearch is None:
        return
    source_id, page_id = str(page["web_source_id"]), str(page["web_page_id"])
    document = {
        **page,
        # Standard ingestion replaces records by content-document ID. Keep the
        # durable manifest under a separate ID so its state survives re-ingestion.
        "document_id": page_manifest_id(source_id, page_id),
        "content_document_id": page.get("content_document_id") or page.get("document_id"),
        "record_kind": PAGE_MANIFEST_KIND,
        "connector_type": "url",
        "indexed_time": datetime.now(UTC).isoformat(),
    }
    await clients.opensearch.index(
        index=get_index_name(),
        id=page_manifest_id(source_id, page_id),
        body=document,
        refresh=True,
    )


async def upsert_source_manifest(
    source: dict[str, Any], *, pages: Iterable[dict[str, Any]] | None = None
) -> None:
    """Persist a source's configuration, lifecycle, and Knowledge-row summary."""
    if clients.opensearch is None:
        return
    source_id = str(source["id"])
    page_list = list(pages) if pages is not None else None
    active_pages = (
        [page for page in page_list if page.get("status") == "active"]
        if page_list is not None
        else []
    )
    metadata_page = (
        next(
            (page for page in active_pages if page.get("embedding_model")),
            next((page for page in page_list or [] if page.get("embedding_model")), {}),
        )
        if page_list is not None
        else source
    )
    document = {
        **source,
        "id": source_id,
        "document_id": source_manifest_id(source_id),
        "filename": source["name"],
        "mimetype": "text/html",
        "file_size": (
            sum(int(page.get("file_size") or 0) for page in active_pages)
            if page_list is not None
            else source.get("file_size", 0)
        ),
        "source_url": source["starting_url"],
        "root_source_url": source["starting_url"],
        "connector_type": "url",
        "record_kind": SOURCE_MANIFEST_KIND,
        "web_source_id": source_id,
        "web_child_count": len(page_list)
        if page_list is not None
        else source.get("web_child_count", 0),
        "chunk_count": (
            sum(int(page.get("chunk_count") or 0) for page in active_pages)
            if page_list is not None
            else source.get("chunk_count", 0)
        ),
        "embedding_model": metadata_page.get("embedding_model", ""),
        "embedding_provider": metadata_page.get("embedding_provider", ""),
        "embedding_space_id": metadata_page.get("embedding_space_id", ""),
        "embedding_dimensions": metadata_page.get("embedding_dimensions"),
        "owner": source["owner_id"],
        "owner_id": source["owner_id"],
        "owner_name": source.get("owner_name", ""),
        "owner_email": source.get("owner_email", ""),
        "allowed_users": source.get("allowed_users", []),
        "allowed_groups": source.get("allowed_groups", []),
        "allowed_principal_labels": source.get("allowed_principal_labels", []),
        "error": source.get("last_error") or "",
        "indexed_time": datetime.now(UTC).isoformat(),
    }
    await clients.opensearch.index(
        index=get_index_name(), id=source_manifest_id(source_id), body=document, refresh=True
    )


async def delete_source_projection(source_id: str) -> None:
    if clients.opensearch is None:
        return
    try:
        await clients.opensearch.delete(
            index=get_index_name(), id=source_manifest_id(source_id), refresh=True
        )
    except Exception:
        return


async def delete_page_chunks(document_id: str) -> int:
    if clients.opensearch is None:
        return 0
    from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids

    ids = await collect_visible_document_ids(
        clients.opensearch,
        index=get_index_name(),
        query={"term": {"document_id": document_id}},
    )
    return await delete_document_ids(clients.opensearch, index=get_index_name(), document_ids=ids)


async def delete_source_chunks(source_id: str) -> int:
    if clients.opensearch is None:
        return 0
    from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids

    ids = await collect_visible_document_ids(
        clients.opensearch,
        index=get_index_name(),
        query={"bool": {"filter": [_exact("web_source_id", source_id)]}},
    )
    return await delete_document_ids(clients.opensearch, index=get_index_name(), document_ids=ids)
