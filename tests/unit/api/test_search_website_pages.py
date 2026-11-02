import json
from unittest.mock import AsyncMock

import pytest

from api import search as search_api
from api.search import SearchBody, _website_page_search_result
from auth_context import get_search_filters, set_search_filters
from services.search_service import (
    SearchService,
    _build_search_filter_clauses,
)


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
async def test_search_clears_filters_when_the_request_has_none():
    service = object.__new__(SearchService)
    service.search_tool = AsyncMock(return_value={})
    set_search_filters({"web_source_ids": ["source-1"]})

    await service.search("guide", filters=None)

    assert get_search_filters() == {}


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
async def test_website_page_search_merges_content_hits_into_manifest_rows(monkeypatch):
    source = {"id": "source-1", "owner_id": "user-1"}
    manifests = [
        {
            "web_source_id": source["id"],
            "web_page_id": "page-active",
            "content_document_id": "doc-active",
            "filename": "Guide",
            "source_url": "https://docs.example.com/guide",
            "chunk_count": 2,
            "status": "active",
        },
        {
            "web_source_id": source["id"],
            "web_page_id": "page-disabled",
            "content_document_id": "doc-disabled",
            "filename": "Archived guide",
            "source_url": "https://docs.example.com/archived",
            "chunk_count": 0,
            "status": "disabled",
        },
    ]
    search_service = type(
        "SearchService",
        (),
        {
            "search": AsyncMock(
                return_value={
                    "results": [
                        {
                            "web_source_id": source["id"],
                            "web_page_id": "page-active",
                            "score": 0.9,
                            "highlights": ["<mark>Baseball</mark> guide"],
                        },
                        # Parent source hits are not page-table rows.
                        {"web_source_id": source["id"], "score": 1.0},
                    ]
                }
            )
        },
    )()
    monkeypatch.setattr(search_api, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(search_api, "list_page_manifests", AsyncMock(side_effect=[manifests, []]))

    result = await _website_page_search_result(
        SearchBody(
            query="baseball",
            filters={"web_source_ids": [source["id"]]},
            resultMode="website_pages",
        ),
        type("User", (), {"user_id": source["owner_id"], "jwt_token": None})(),
        search_service,
    )

    assert [page["web_page_id"] for page in result["results"]] == ["page-active"]
    matched_page = result["results"][0]
    assert matched_page["status"] == "active"
    assert matched_page["chunk_count"] == 2
    assert matched_page["score"] == 0.9
    assert matched_page["highlights"] == ["<mark>Baseball</mark> guide"]
    assert search_service.search.await_args.kwargs["result_mode"] == "chunks"


@pytest.mark.asyncio
async def test_root_knowledge_search_aggregates_child_page_hits_under_their_source(monkeypatch):
    source = {
        "id": "source-1",
        "owner_id": "user-1",
        "name": "MLB",
        "starting_url": "https://www.mlb.com",
        "filename": "MLB",
        "mimetype": "text/html",
        "file_size": 4096,
        "chunk_count": 4,
        "web_child_count": 1,
        "status": "active",
    }
    search_service = type(
        "SearchService",
        (),
        {
            "search": AsyncMock(
                return_value={
                    "results": [
                        {
                            "filename": "Baseball news",
                            "text": "Baseball highlights",
                            "score": 0.9,
                            "connector_type": "url",
                            "web_source_id": "source-1",
                            "web_page_id": "page-1",
                        },
                        {"filename": "Document.pdf", "score": 0.5},
                    ],
                    "total": 2,
                }
            )
        },
    )()
    user = type("User", (), {"user_id": "user-1", "jwt_token": None})()
    monkeypatch.setattr(search_api, "get_source_manifest", AsyncMock(return_value=source))

    response = await search_api.search(
        SearchBody(query="baseball", resultMode="knowledge_sources"),
        search_service=search_service,
        user=user,
    )

    body = json.loads(response.body)
    assert [result["filename"] for result in body["results"]] == ["MLB", "Document.pdf"]
    assert body["results"][0]["web_source_id"] == "source-1"
    assert body["results"][0].get("web_page_id") is None
    assert body["results"][0]["score"] == 0.9
    assert body["total"] == 2
    assert search_service.search.await_args.kwargs["result_mode"] == "knowledge_sources"


@pytest.mark.asyncio
async def test_knowledge_source_search_applies_limit_after_website_grouping(monkeypatch):
    sources = {
        "source-1": {"id": "source-1", "owner_id": "user-1", "name": "First"},
        "source-2": {"id": "source-2", "owner_id": "user-1", "name": "Second"},
    }
    search_service = type(
        "SearchService",
        (),
        {
            "search": AsyncMock(
                return_value={
                    "results": [
                        {
                            "filename": "First page",
                            "score": 0.9,
                            "web_source_id": "source-1",
                            "web_page_id": "page-1",
                        },
                        {
                            "filename": "Second page",
                            "score": 0.8,
                            "web_source_id": "source-2",
                            "web_page_id": "page-2",
                        },
                        {"filename": "Document.pdf", "score": 0.7},
                    ]
                }
            )
        },
    )()
    user = type("User", (), {"user_id": "user-1", "jwt_token": None})()
    monkeypatch.setattr(
        search_api,
        "get_source_manifest",
        AsyncMock(side_effect=lambda source_id: sources[source_id]),
    )

    response = await search_api.search(
        SearchBody(query="guide", limit=2, resultMode="knowledge_sources"),
        search_service=search_service,
        user=user,
    )

    body = json.loads(response.body)
    assert [result["filename"] for result in body["results"]] == ["First", "Second"]
    assert body["total"] == 2
    # It requests a wider candidate set before grouping, then returns the requested two sources.
    assert search_service.search.await_args.kwargs["limit"] == 100


@pytest.mark.asyncio
async def test_knowledge_source_search_keeps_fetching_when_one_source_fills_candidate_set(
    monkeypatch,
):
    sources = {
        "source-1": {"id": "source-1", "owner_id": "user-1", "name": "First"},
        "source-2": {"id": "source-2", "owner_id": "user-1", "name": "Second"},
    }

    def page_hit(source_id: str, page_number: int) -> dict:
        return {
            "score": 1 - page_number / 1_000,
            "web_source_id": source_id,
            "web_page_id": f"{source_id}-page-{page_number}",
        }

    first_candidate_set = [page_hit("source-1", number) for number in range(100)]
    expanded_candidate_set = [
        *[page_hit("source-1", number) for number in range(100)],
        page_hit("source-2", 0),
    ]
    search_service = type(
        "SearchService",
        (),
        {
            "search": AsyncMock(
                side_effect=[{"results": first_candidate_set}, {"results": expanded_candidate_set}]
            )
        },
    )()
    user = type("User", (), {"user_id": "user-1", "jwt_token": None})()
    monkeypatch.setattr(
        search_api,
        "get_source_manifest",
        AsyncMock(side_effect=lambda source_id: sources[source_id]),
    )

    response = await search_api.search(
        SearchBody(query="guide", limit=2, resultMode="knowledge_sources"),
        search_service=search_service,
        user=user,
    )

    body = json.loads(response.body)
    assert [result["filename"] for result in body["results"]] == ["First", "Second"]
    assert [call.kwargs["limit"] for call in search_service.search.await_args_list] == [100, 200]
