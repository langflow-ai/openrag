"""Tests for preview-mode Docling conversion options (layout visual parser)."""

from unittest.mock import patch

import pytest

from services.docling_service import DoclingService


@pytest.fixture
def docling_service():
    return DoclingService(docling_url="http://docling:8000", httpx_client=None)


def test_build_docling_options_default_uses_placeholder_images(docling_service):
    with patch("services.docling_service.get_openrag_config") as mock_cfg:
        mock_cfg.return_value.knowledge.table_structure = False
        mock_cfg.return_value.knowledge.ocr = False
        mock_cfg.return_value.knowledge.picture_descriptions = False

        options = docling_service._build_docling_options()

    assert options["to_formats"] == "json"
    assert options["image_export_mode"] == "placeholder"


def test_build_docling_options_preview_uses_embedded_images(docling_service):
    with patch("services.docling_service.get_openrag_config") as mock_cfg:
        mock_cfg.return_value.knowledge.table_structure = True
        mock_cfg.return_value.knowledge.ocr = False
        mock_cfg.return_value.knowledge.picture_descriptions = False

        options = docling_service._build_docling_options(preview_mode=True)

    assert options["to_formats"] == "json"
    assert options["image_export_mode"] == "embedded"
    assert options["do_table_structure"] is True
    # docling-img needs full-page renderings (and picture images) embedded in
    # the JSON to draw bounding boxes; these are off by default in docling-serve.
    assert options["include_page_images"] is True
    assert options["include_images"] is True


def test_build_docling_options_default_omits_page_images(docling_service):
    with patch("services.docling_service.get_openrag_config") as mock_cfg:
        mock_cfg.return_value.knowledge.table_structure = False
        mock_cfg.return_value.knowledge.ocr = False
        mock_cfg.return_value.knowledge.picture_descriptions = False

        options = docling_service._build_docling_options()

    assert "include_page_images" not in options


@pytest.mark.asyncio
async def test_upload_to_docling_preview_passes_embedded_mode():
    from unittest.mock import AsyncMock, MagicMock

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"task_id": "docling-task-1"}
    mock_response.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    service = DoclingService(docling_url="http://docling:8000", httpx_client=mock_client)

    with patch("services.docling_service.get_openrag_config") as mock_cfg:
        mock_cfg.return_value.knowledge.table_structure = True
        mock_cfg.return_value.knowledge.ocr = False
        mock_cfg.return_value.knowledge.picture_descriptions = False

        task_id = await service.upload_to_docling_direct_async(
            "sample.pdf",
            b"%PDF-1.4",
            preview_mode=True,
        )

    assert task_id == "docling-task-1"
    _args, kwargs = mock_client.post.call_args
    data = kwargs["data"]
    assert data["image_export_mode"] == "embedded"
    assert data["do_table_structure"] == "true"
    assert data["include_page_images"] == "true"
    assert data["include_images"] == "true"
