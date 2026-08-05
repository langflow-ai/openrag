"""Integration tests for client.documents.list_files().

These tests require a running OpenRAG instance and at least one ingested file.
They are skipped when SKIP_SDK_INTEGRATION_TESTS=true (CI without a live stack).
"""

import json
import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestListFiles:
    """Verify GET /v1/files via the Python SDK."""

    @pytest.mark.asyncio
    async def test_list_files_returns_valid_response_shape(self, client, test_file: Path):
        """list_files() returns a ListFilesResponse with required fields."""
        # Ingest a file so there is at least one result
        await client.documents.ingest(file_path=str(test_file))
        try:
            result = await client.documents.list_files(page_size=10)

            assert result.total >= 0
            assert isinstance(result.is_approximate, bool)
            assert result.page == 1
            assert result.page_size == 10
            assert isinstance(result.files, list)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_list_files_record_has_all_knowledge_filter_fields(
        self, client, test_file: Path
    ):
        """Each FileRecord contains the fields needed to build a knowledge filter."""
        await client.documents.ingest(file_path=str(test_file))
        try:
            result = await client.documents.list_files(search=test_file.stem)
            assert len(result.files) >= 1, "Expected the ingested file to appear in results"

            f = result.files[0]
            # Core identity fields
            assert isinstance(f.filename, str) and f.filename
            assert isinstance(f.document_id, str)
            # Fields needed to build queryData.filters
            assert isinstance(f.connector_type, str)
            assert isinstance(f.mimetype, str)
            assert isinstance(f.owner, str)
            # Pagination / metadata fields
            assert isinstance(f.chunk_count, int) and f.chunk_count >= 0
            assert isinstance(f.file_size, int) and f.file_size >= 0
            assert isinstance(f.indexed_time, str) and f.indexed_time
            # ACL fields (may be empty lists but must be present)
            assert isinstance(f.allowed_users, list)
            assert isinstance(f.allowed_groups, list)
            assert isinstance(f.allowed_principal_labels, list)
        finally:
            await client.documents.delete(test_file.name)

    @pytest.mark.asyncio
    async def test_list_files_pagination(self, client, tmp_path: Path):
        """page_size is respected and after_key enables cursor navigation."""
        token = uuid.uuid4().hex[:8]
        files = []
        for i in range(3):
            p = tmp_path / f"pg_{token}_{i}.md"
            p.write_text(f"# Page test {i}\n\nContent {uuid.uuid4()}.\n")
            await client.documents.ingest(file_path=str(p))
            files.append(p)

        try:
            page1 = await client.documents.list_files(page_size=2)
            assert len(page1.files) <= 2

            if page1.after_key is not None:
                page2 = await client.documents.list_files(
                    page_size=2,
                    after_key=json.dumps(page1.after_key),
                )
                assert isinstance(page2.files, list)
                # Pages must not overlap by filename
                p1_names = {f.filename for f in page1.files}
                p2_names = {f.filename for f in page2.files}
                assert p1_names.isdisjoint(p2_names), (
                    f"Pages overlap: {p1_names & p2_names}"
                )
        finally:
            for p in files:
                await client.documents.delete(p.name)

    @pytest.mark.asyncio
    async def test_list_files_search_filters_by_filename(self, client, tmp_path: Path):
        """search= parameter filters results to filenames matching the query."""
        token = uuid.uuid4().hex[:8]
        needle = tmp_path / f"needle_{token}.md"
        haystack = tmp_path / f"haystack_{token}.md"
        needle.write_text("# Needle\n\nUnique needle content.\n")
        haystack.write_text("# Haystack\n\nUnrelated haystack content.\n")

        await client.documents.ingest(file_path=str(needle))
        await client.documents.ingest(file_path=str(haystack))

        try:
            result = await client.documents.list_files(search=f"needle_{token}")
            filenames = [f.filename for f in result.files]
            assert any(f"needle_{token}" in fn for fn in filenames), (
                f"Expected needle_{token} in results, got: {filenames}"
            )
            assert not any(f"haystack_{token}" in fn for fn in filenames), (
                f"Haystack should not appear in needle search, got: {filenames}"
            )
        finally:
            await client.documents.delete(needle.name)
            await client.documents.delete(haystack.name)

    @pytest.mark.asyncio
    async def test_list_then_create_filter_workflow(self, client, test_file: Path):
        """Filenames from list_files can be used directly as knowledge filter data_sources."""
        await client.documents.ingest(file_path=str(test_file))
        filter_id = None

        try:
            page = await client.documents.list_files(search=test_file.stem)
            assert len(page.files) >= 1, "Ingested file must appear in list"

            filenames = [f.filename for f in page.files]
            result = await client.knowledge_filters.create({
                "name": f"list-then-filter {uuid.uuid4().hex[:6]}",
                "description": "Created by SDK list_files integration test",
                "queryData": {
                    "query": "",
                    "filters": {
                        "data_sources": filenames,
                        "document_types": ["*"],
                        "owners": ["*"],
                        "connector_types": ["*"],
                    },
                    "limit": 10,
                    "scoreThreshold": 0,
                },
            })
            assert result.success is True
            assert result.id is not None
            filter_id = result.id
        finally:
            if filter_id:
                await client.knowledge_filters.delete(filter_id)
            await client.documents.delete(test_file.name)
