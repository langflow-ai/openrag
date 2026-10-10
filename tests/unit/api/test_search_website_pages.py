import json
from unittest.mock import AsyncMock

import pytest

from api import search as search_api
from api.search import SearchBody, _website_page_search_result
from services.search_service import _build_search_filter_clauses


def test_url_source_filter_matches_current_and_legacy_keyword_mappings():
    clauses = _build_search_filter_clauses({"web_source_ids": ["website-123"]})

    assert clauses == [
        {
            "bool": {
                "should": [
                    {"term": {"web_source_id": "website-123"}},
                    {"term": {"web_source_id.keyword": "website-123"}},
                ],
                "minimum_should_match": 1,
            }
        }
    ]


@pytest.mark.asyncio
async def test_website_page_search_reads_zero_chunk_manifest_rows(monkeypatch):
    source = {"id": "source-1", "owner_id": "user-1"}
    manifests = [
        {
            "web_source_id": source["id"],
            "web_page_id": "page-active",
            "document_id": "web-page:source-1:active",
            "content_document_id": "doc-active",
            "canonical_url": "https://docs.example.com/guide",
            "source_url": "https://docs.example.com/guide",
            "filename": "Guide",
            "file_size": 1024,
            "chunk_count": 2,
            "status": "active",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
        },
        {
            "web_source_id": source["id"],
            "web_page_id": "page-disabled",
            "document_id": "web-page:source-1:disabled",
            "content_document_id": "doc-disabled",
            "canonical_url": "https://docs.example.com/archived",
            "filename": "Archived guide",
            "chunk_count": 0,
            "status": "disabled",
        },
    ]
    monkeypatch.setattr(search_api, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(search_api, "list_page_manifests", AsyncMock(return_value=manifests))

    result = await _website_page_search_result(
        SearchBody(
            query="*",
            filters={"web_source_ids": [source["id"]]},
            resultMode="website_pages",
        ),
        type("User", (), {"user_id": source["owner_id"]})(),
    )

    by_document = {chunk["document_id"]: chunk for chunk in result["results"]}
    assert by_document["doc-active"]["embedding_dimensions"] == 1536
    assert by_document["doc-active"]["chunk_count"] == 2
    assert by_document["doc-disabled"]["status"] == "disabled"
    assert by_document["doc-disabled"]["chunk_count"] == 0


@pytest.mark.asyncio
async def test_root_knowledge_search_excludes_child_page_hits():
    search_service = type(
        "SearchService",
        (),
        {
            "search": AsyncMock(
                return_value={
                    "results": [
                        {
                            "filename": "Child page",
                            "web_source_id": "source-1",
                            "web_page_id": "page-1",
                        },
                        {"filename": "Document.pdf"},
                    ],
                    "total": 2,
                }
            )
        },
    )()
    user = type("User", (), {"user_id": "user-1", "jwt_token": None})()

    response = await search_api.search(
        SearchBody(query="guide", resultMode="knowledge_sources"),
        search_service=search_service,
        user=user,
    )

    body = json.loads(response.body)
    assert body["results"] == [{"filename": "Document.pdf"}]
    assert body["total"] == 1
