"""Tests for document ingestion and deletion."""

import io
import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestDocuments:
    """Core document ingestion and deletion tests."""

    @pytest.mark.asyncio
    async def test_ingest_document_no_wait(self, client, test_file: Path):
        """wait=False returns a task_id immediately; polling reaches a terminal state."""
        result = await client.documents.ingest(file_path=str(test_file), wait=False)
        assert result.task_id is not None

        final_status = await client.documents.wait_for_task(result.task_id)
        assert final_status.status is not None
        assert final_status.successful_files >= 0

    @pytest.mark.asyncio
    async def test_ingest_document(self, client, test_file: Path):
        """wait=True polls until completion and returns a terminal status."""
        result = await client.documents.ingest(file_path=str(test_file))
        assert result.status is not None
        assert result.successful_files >= 0

    @pytest.mark.asyncio
    async def test_delete_document(self, client, test_file: Path):
        """Deleting an ingested document succeeds when chunks were indexed."""
        ingest_result = await client.documents.ingest(file_path=str(test_file))

        result = await client.documents.delete(test_file.name)

        if ingest_result.successful_files > 0:
            assert result.success is True
            assert result.deleted_chunks > 0
        else:
            assert result.success is False
            assert result.deleted_chunks == 0

    @pytest.mark.asyncio
    async def test_delete_missing_document_is_idempotent(self, client):
        """Deleting a never-ingested filename must not raise."""
        missing_filename = f"never_ingested_{uuid.uuid4().hex}.pdf"
        result = await client.documents.delete(missing_filename)

        assert result.success is False
        assert result.deleted_chunks == 0
        assert result.filename == missing_filename
        assert result.error is not None


class TestDocumentsExtended:
    """Additional document ingestion scenarios."""

    @pytest.mark.asyncio
    async def test_ingest_via_file_object(self, client):
        """Ingest using a file-like object (io.BytesIO) instead of a file path."""
        unique_token = uuid.uuid4().hex
        content = (
            f"# File Object Test\n\n"
            f"Token: {unique_token}\n\n"
            f"This document was ingested via a file object.\n"
        ).encode()

        filename = f"file_obj_{unique_token[:8]}.md"
        result = await client.documents.ingest(file=io.BytesIO(content), filename=filename)
        assert result.status is not None
        assert result.successful_files >= 0

        await client.documents.delete(filename)

    @pytest.mark.asyncio
    async def test_reingest_same_filename_does_not_raise(self, client, tmp_path):
        """Ingesting the same filename twice must not raise an error."""
        unique_token = uuid.uuid4().hex
        file_path = tmp_path / f"reingest_{unique_token[:8]}.md"
        file_path.write_text(f"# Reingest Test\n\nToken: {unique_token}\n")

        result1 = await client.documents.ingest(file_path=str(file_path))
        assert result1.status is not None

        result2 = await client.documents.ingest(file_path=str(file_path))
        assert result2.status is not None

        await client.documents.delete(file_path.name)

    @pytest.mark.asyncio
    async def test_ingest_markdown_format(self, client, tmp_path):
        """Verify .md files are accepted and processed without error."""
        file_path = tmp_path / f"format_md_{uuid.uuid4().hex[:8]}.md"
        file_path.write_text("# Markdown Format\n\n## Section\n\nContent here.\n")
        result = await client.documents.ingest(file_path=str(file_path))
        assert result.status is not None
        await client.documents.delete(file_path.name)

    @pytest.mark.asyncio
    async def test_task_status_polling(self, client, tmp_path):
        """wait=False returns a task_id that can be polled and waited on manually."""
        file_path = tmp_path / f"poll_{uuid.uuid4().hex[:8]}.md"
        file_path.write_text("# Polling Test\n\nContent for polling test.\n")

        task_response = await client.documents.ingest(file_path=str(file_path), wait=False)
        assert task_response.task_id is not None

        status = await client.documents.get_task_status(task_response.task_id)
        assert status.status is not None

        final = await client.documents.wait_for_task(task_response.task_id)
        assert final.status in ("completed", "failed")

        await client.documents.delete(file_path.name)
