from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.search import SearchBody, _website_page_search_result
from db.models.website_source import WebsitePage, WebsiteSource
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
async def test_website_page_search_hydrates_search_hits_and_zero_chunk_pages():
    source = WebsiteSource(
        id="source-1",
        owner_id="user-1",
        name="Docs",
        starting_url="https://docs.example.com",
        crawl_settings={},
    )
    active = WebsitePage(
        id="page-active",
        web_source_id=source.id,
        canonical_url="https://docs.example.com/guide",
        title="Guide",
        document_id="doc-active",
        byte_size=1024,
        chunk_count=2,
        status="active",
    )
    disabled = WebsitePage(
        id="page-disabled",
        web_source_id=source.id,
        canonical_url="https://docs.example.com/archived",
        title="Archived guide",
        document_id="doc-disabled",
        chunk_count=0,
        status="disabled",
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=source),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [active, disabled])
            )
        ),
    )
    result = await _website_page_search_result(
        {
            "results": [
                {
                    "document_id": active.document_id,
                    "text": "The guide content",
                    "score": 3.5,
                    "filename": "stale title",
                }
            ]
        },
        SearchBody(
            query="*",
            filters={"web_source_ids": [source.id]},
            resultMode="website_pages",
        ),
        session,
        SimpleNamespace(user_id=source.owner_id),
    )

    by_document = {chunk["document_id"]: chunk for chunk in result["results"]}
    assert by_document[active.document_id] == {
        "document_id": active.document_id,
        "text": "The guide content",
        "score": 3.5,
        "filename": active.title,
        "mimetype": "text/html",
        "source_url": active.canonical_url,
        "file_size": active.byte_size,
        "connector_type": "url",
        "web_source_id": source.id,
        "web_page_id": active.id,
        "web_page_depth": active.depth,
        "canonical_url": active.canonical_url,
        "status": "active",
        "error": None,
        "chunk_count": active.chunk_count,
    }
    assert by_document[disabled.document_id]["status"] == "disabled"
    assert by_document[disabled.document_id]["chunk_count"] == 0
