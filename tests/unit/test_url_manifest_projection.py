from unittest.mock import AsyncMock

import pytest

from config.settings import clients
from connectors.url.projection import upsert_page_manifest, upsert_source_manifest


@pytest.mark.asyncio
async def test_page_manifest_is_non_vector_and_parent_projection_aggregates_pages(monkeypatch):
    opensearch = type("OpenSearch", (), {"index": AsyncMock()})()
    monkeypatch.setattr(clients, "opensearch", opensearch)
    page = {
        "web_source_id": "source-1",
        "web_page_id": "page-1",
        "content_document_id": "document-1",
        "canonical_url": "https://docs.example.com/guide",
        "chunk_count": 4,
        "file_size": 512,
        "status": "active",
        "embedding_model": "text-embedding-3-small",
        "embedding_provider": "azure",
        "embedding_dimensions": 1536,
    }
    source = {
        "id": "source-1",
        "owner_id": "owner-1",
        "name": "Documentation",
        "starting_url": "https://docs.example.com/",
        "crawl_settings": {"seed_url": "https://docs.example.com/"},
        "change_detection": "normalized_content_hash",
        "resync_behavior": "full",
        "removed_page_behavior": "retain",
        "status": "active",
        "deleting": False,
    }

    await upsert_page_manifest(page)
    page_call, source_call = opensearch.index.await_args_list[0], None
    assert page_call.kwargs["id"] == "web-page:source-1:page-1"
    assert page_call.kwargs["body"]["record_kind"] == "web_page_manifest"
    assert page_call.kwargs["body"]["document_id"] == "web-page:source-1:page-1"
    assert page_call.kwargs["body"]["content_document_id"] == "document-1"

    await upsert_source_manifest(source, pages=[page])
    source_call = opensearch.index.await_args_list[1]
    parent = source_call.kwargs["body"]
    assert parent["record_kind"] == "web_source"
    assert parent["chunk_count"] == 4
    assert parent["file_size"] == 512
    assert parent["embedding_dimensions"] == 1536
    assert parent["crawl_settings"] == source["crawl_settings"]
