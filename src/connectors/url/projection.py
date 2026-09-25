"""Non-vector source projection used by the root Knowledge table."""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import clients, get_index_name
from db.models.website_source import WebsiteSource


async def upsert_source_projection(source: WebsiteSource, *, child_count: int = 0) -> None:
    if clients.opensearch is None:
        return
    document = {
        "document_id": f"web-source:{source.id}",
        "filename": source.name,
        "mimetype": "text/html",
        "file_size": 0,
        "source_url": source.starting_url,
        "root_source_url": source.starting_url,
        "connector_type": "url",
        "record_kind": "web_source",
        "web_source_id": source.id,
        "web_child_count": child_count,
        "status": source.status,
        "error": source.last_error or "",
        "owner": source.owner_id,
        "indexed_time": datetime.now(UTC).isoformat(),
    }
    await clients.opensearch.index(
        index=get_index_name(), id=f"web-source:{source.id}", body=document, refresh=True
    )


async def delete_source_projection(source_id: str) -> None:
    if clients.opensearch is None:
        return
    try:
        await clients.opensearch.delete(
            index=get_index_name(), id=f"web-source:{source_id}", refresh=True
        )
    except Exception:
        # A missing projection should not block SQL cleanup.
        return


async def delete_page_chunks(document_id: str) -> int:
    """Delete only the concrete child chunks for a stable website document."""
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
        query={
            "bool": {
                "should": [
                    {"term": {"web_source_id": source_id}},
                    {"term": {"web_source_id.keyword": source_id}},
                ],
                "minimum_should_match": 1,
            }
        },
    )
    return await delete_document_ids(clients.opensearch, index=get_index_name(), document_ids=ids)
