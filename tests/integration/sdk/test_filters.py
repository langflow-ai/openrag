"""Tests for knowledge filter CRUD and usage in chat/search.

The filter_id usage tests (everything below TestKnowledgeFilters) verify that
a filter actually constrains the search to the filenames in its `data_sources`,
not just that the parameter is accepted without error.
"""

import os
import uuid
from pathlib import Path

import pytest
from openrag_sdk.exceptions import OpenRAGError

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


def _make_doc(tmp_path: Path, label: str, animal: str) -> Path:
    """Write a unique markdown file mentioning `animal`. Returns the path."""
    token = uuid.uuid4().hex[:8]
    path = tmp_path / f"{label}_{token}.md"
    path.write_text(
        f"# {label.title()} doc {token}\n\n"
        f"This document discusses {animal}.\n"
        "It is used only for SDK filter integration tests.\n"
    )
    return path


async def _ingest_pair(client, tmp_path: Path) -> tuple[Path, Path]:
    """Ingest two distinguishable documents and return their paths."""
    alpha = _make_doc(tmp_path, "alpha", "purple elephants")
    beta = _make_doc(tmp_path, "beta", "yellow tigers")
    await client.documents.ingest(file_path=str(alpha))
    await client.documents.ingest(file_path=str(beta))
    return alpha, beta


async def _create_filter_for(client, name: str, data_sources: list[str]) -> str:
    """Create a knowledge filter scoped to the given filenames. Returns filter_id."""
    result = await client.knowledge_filters.create(
        {
            "name": name,
            "description": f"Auto-created by SDK test ({uuid.uuid4().hex[:6]})",
            "queryData": {
                "query": "",
                "filters": {
                    "data_sources": data_sources,
                    "document_types": ["*"],
                    "owners": ["*"],
                    "connector_types": ["*"],
                },
                "limit": 10,
                "scoreThreshold": 0,
            },
        }
    )
    assert result.success is True, f"Failed to create filter: {result.error}"
    return result.id


class TestKnowledgeFilters:
    """Test knowledge filter create, read, update, delete and usage."""

    @pytest.mark.asyncio
    async def test_knowledge_filter_crud(self, client):
        """Full CRUD lifecycle for a knowledge filter."""
        create_result = await client.knowledge_filters.create(
            {
                "name": "Python SDK Test Filter",
                "description": "Filter created by Python SDK integration tests",
                "queryData": {
                    "query": "test documents",
                    "limit": 10,
                    "scoreThreshold": 0.5,
                },
            }
        )
        assert create_result.success is True
        assert create_result.id is not None
        filter_id = create_result.id

        # Search
        filters = await client.knowledge_filters.search("Python SDK Test")
        assert isinstance(filters, list)
        assert any(f.name == "Python SDK Test Filter" for f in filters)

        # Get
        filter_obj = await client.knowledge_filters.get(filter_id)
        assert filter_obj is not None
        assert filter_obj.id == filter_id
        assert filter_obj.name == "Python SDK Test Filter"

        # Update
        update_success = await client.knowledge_filters.update(
            filter_id,
            {"description": "Updated description from Python SDK test"},
        )
        assert update_success is True

        updated_filter = await client.knowledge_filters.get(filter_id)
        assert updated_filter.description == "Updated description from Python SDK test"

        # Delete
        delete_success = await client.knowledge_filters.delete(filter_id)
        assert delete_success is True

        deleted_filter = await client.knowledge_filters.get(filter_id)
        assert deleted_filter is None


class TestFilterIdInChat:
    """Verify filter_id actually constrains chat retrieval, not just that it's accepted."""

    @pytest.mark.asyncio
    async def test_filter_id_in_chat_actually_filters(self, client, tmp_path):
        """Sources returned must only include the file in the filter's data_sources."""
        alpha, beta = await _ingest_pair(client, tmp_path)
        filter_id = await _create_filter_for(client, "SDK chat filter scope", [alpha.name])

        try:
            response = await client.chat.create(
                message="What animals appear in these documents?",
                filter_id=filter_id,
            )
            assert response.sources is not None
            source_names = [s.filename for s in response.sources]
            # Beta must NOT appear; alpha may or may not (RAG can return empty),
            # but anything that does come back must be alpha.
            assert beta.name not in source_names, f"Filter leaked: beta in sources {source_names}"
        finally:
            await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)

    @pytest.mark.asyncio
    async def test_filter_id_in_chat_inline_overrides(self, client, tmp_path):
        """Inline `filters` win over filter_id per the v1 override contract."""
        alpha, beta = await _ingest_pair(client, tmp_path)
        filter_id = await _create_filter_for(client, "SDK chat inline-override", [alpha.name])

        try:
            response = await client.chat.create(
                message="What animals appear in these documents?",
                filter_id=filter_id,
                filters={"data_sources": [beta.name]},
            )
            assert response.sources is not None
            source_names = [s.filename for s in response.sources]
            assert alpha.name not in source_names, (
                f"Inline override didn't win: alpha in sources {source_names}"
            )
        finally:
            await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)

    @pytest.mark.asyncio
    async def test_filter_id_in_chat_streaming_also_filters(self, client, tmp_path):
        """Streaming path must apply the resolved filter just like non-streaming."""
        alpha, beta = await _ingest_pair(client, tmp_path)
        filter_id = await _create_filter_for(client, "SDK chat stream filter", [alpha.name])

        try:
            collected_sources: list[str] = []
            async for event in await client.chat.create(
                message="What animals appear in these documents?",
                filter_id=filter_id,
                stream=True,
            ):
                if event.type == "sources":
                    collected_sources.extend(s.filename for s in event.sources)

            assert beta.name not in collected_sources, (
                f"Streaming filter leaked: beta in {collected_sources}"
            )
        finally:
            await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)

    @pytest.mark.asyncio
    async def test_filter_id_not_found_chat(self, client):
        """A non-existent filter_id surfaces as a 404-class error."""
        with pytest.raises(OpenRAGError):
            await client.chat.create(
                message="hi",
                filter_id=f"does-not-exist-{uuid.uuid4().hex}",
            )


class TestFilterIdInSearch:
    """Verify filter_id actually constrains search results."""

    @pytest.mark.asyncio
    async def test_filter_id_in_search_actually_filters(self, client, tmp_path):
        """All search results must come from the filter's data_sources only."""
        alpha, beta = await _ingest_pair(client, tmp_path)
        filter_id = await _create_filter_for(client, "SDK search filter scope", [alpha.name])

        try:
            results = await client.search.query("animals", filter_id=filter_id)
            assert results.results is not None
            for r in results.results:
                assert r.filename != beta.name, (
                    f"Filter leaked: search returned beta ({r.filename})"
                )
        finally:
            await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)

    @pytest.mark.asyncio
    async def test_filter_id_in_search_inline_overrides(self, client, tmp_path):
        """Inline filters override the resolved filter_id per-field."""
        alpha, beta = await _ingest_pair(client, tmp_path)
        filter_id = await _create_filter_for(client, "SDK search inline-override", [alpha.name])

        try:
            results = await client.search.query(
                "animals",
                filter_id=filter_id,
                filters={"data_sources": [beta.name]},
            )
            for r in results.results:
                assert r.filename != alpha.name, (
                    f"Inline override didn't win: search returned alpha ({r.filename})"
                )
        finally:
            await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(alpha.name)
            await client.documents.delete(beta.name)

    @pytest.mark.asyncio
    async def test_filter_id_not_found_search(self, client):
        """A non-existent filter_id on search surfaces as an error."""
        with pytest.raises(OpenRAGError):
            await client.search.query(
                "anything",
                filter_id=f"does-not-exist-{uuid.uuid4().hex}",
            )
