"""Tests that preview-mode ingestion caches Docling JSON after polling succeeds."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ingest_preview_service import IngestPreviewService


@pytest.mark.asyncio
async def test_upload_and_ingest_caches_docling_preview_on_success():
    from services.langflow_file_service import LangflowFileService

    preview_service = IngestPreviewService(ttl_seconds=300)
    docling_service = MagicMock()
    docling_service.upload_to_docling_direct_async = AsyncMock(return_value="docling-1")
    docling_service.fetch_task_result = AsyncMock(
        return_value={
            "pages": [{"page_no": 1}],
            "texts": [],
            "tables": [],
            "pictures": [],
        }
    )

    polling_service = MagicMock()
    from services.docling_polling_service import DoclingPollResult, PollOutcome

    polling_service.poll_until_ready = AsyncMock(
        return_value=DoclingPollResult(outcome=PollOutcome.SUCCESS, elapsed_seconds=1.0)
    )

    langflow_service = LangflowFileService(
        docling_service=docling_service,
        ingest_preview_service=preview_service,
    )
    langflow_service.run_ingestion_flow = AsyncMock(return_value={"status": "success"})

    await langflow_service.upload_and_ingest_file(
        file_tuple=("sample.pdf", b"%PDF", "application/pdf"),
        jwt_token="Bearer tok",
        owner="user-1",
        docling_polling_service=polling_service,
        preview_mode=True,
        upload_task_id="upload-task-1",
        preview_user_id="user-1",
        document_id="hash-abc",
    )

    docling_service.fetch_task_result.assert_awaited_once_with(
        "docling-1",
        user_id="user-1",
        auth_header="Bearer tok",
    )
    cached = preview_service.get_docling_preview("user-1", "upload-task-1")
    assert cached is not None
    assert cached["document"]["pages"] == [{"page_no": 1}]
    assert cached["document_id"] == "hash-abc"
