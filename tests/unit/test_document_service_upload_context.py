"""
Chat uploads (``DocumentService.process_upload_context``) must honor the
app-wide ingestion settings (OCR, table structure, picture descriptions) the
same way knowledge ingestion does, so e.g. an uploaded image yields its
picture description as context (issue #935).
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.docling_service import DoclingService
from services.document_service import DocumentService


class _FakeUpload:
    def __init__(self, data: bytes, filename: str):
        self._buf = io.BytesIO(data)
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


def _knowledge_config(*, ocr: bool, table_structure: bool, picture_descriptions: bool):
    config = MagicMock()
    config.knowledge.ocr = ocr
    config.knowledge.table_structure = table_structure
    config.knowledge.picture_descriptions = picture_descriptions
    config.knowledge.vlm_enabled = False
    config.knowledge.ocr_languages = None
    return config


def _document_service(docling_result: dict) -> tuple[DocumentService, AsyncMock]:
    client = AsyncMock(spec=httpx.AsyncClient)
    upload_response = MagicMock(spec=httpx.Response)
    upload_response.json.return_value = {"task_id": "task-1"}
    upload_response.raise_for_status.return_value = None
    client.post.return_value = upload_response

    docling_service = DoclingService(docling_url="http://docling:8000", httpx_client=client)
    docling_service.get_docling_result_async = AsyncMock(return_value=docling_result)

    service = DocumentService(docling_service=docling_service)
    return service, client


_IMAGE_WITH_DESCRIPTION = {
    "origin": {"binary_hash": "h", "filename": "cat.png", "mimetype": "image/png"},
    "texts": [],
    "tables": [],
    "pictures": [
        {
            "prov": [{"page_no": 1}],
            "annotations": [{"kind": "description", "text": "A red cat on a sofa"}],
        }
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ocr", "table_structure", "picture_descriptions"),
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (False, False, False),
    ],
    ids=["ocr-only", "table-structure-only", "picture-descriptions-only", "all-off"],
)
async def test_upload_context_sends_configured_ingestion_settings_to_docling(
    ocr, table_structure, picture_descriptions
):
    # One setting enabled at a time, so a request field wired to the wrong
    # setting fails instead of passing by coincidence.
    service, client = _document_service(_IMAGE_WITH_DESCRIPTION)
    config = _knowledge_config(
        ocr=ocr, table_structure=table_structure, picture_descriptions=picture_descriptions
    )

    with patch("services.docling_service.get_openrag_config", return_value=config):
        await service.process_upload_context(_FakeUpload(b"png-bytes", "cat.png"), "cat.png")

    data = client.post.call_args.kwargs["data"]
    assert data["do_ocr"] == str(ocr).lower()
    assert data["do_table_structure"] == str(table_structure).lower()
    assert data["do_picture_description"] == str(picture_descriptions).lower()


@pytest.mark.asyncio
async def test_upload_context_returns_picture_description_for_image():
    service, _ = _document_service(_IMAGE_WITH_DESCRIPTION)
    config = _knowledge_config(ocr=False, table_structure=False, picture_descriptions=True)

    with patch("services.docling_service.get_openrag_config", return_value=config):
        result = await service.process_upload_context(
            _FakeUpload(b"png-bytes", "cat.png"), "cat.png"
        )

    assert "A red cat on a sofa" in result["content"]
    assert result["pages"] == 1
