"""Docling OCR settings pushed into the Langflow ingest flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.settings.langflow_sync import _update_langflow_docling_settings


@pytest.mark.asyncio
async def test_langflow_sync_includes_ocr_languages():
    """The ingest flow's docling_serve_opts must carry the configured OCR languages."""
    config = MagicMock()
    config.knowledge.table_structure = False
    config.knowledge.ocr = True
    config.knowledge.ocr_languages = ["en", "ja"]
    config.knowledge.picture_descriptions = False

    flows_service = MagicMock()
    flows_service.update_flow_docling_preset = AsyncMock()

    with patch("services.docling_service.platform.system", return_value="Linux"):
        await _update_langflow_docling_settings(config, flows_service)

    _, opts = flows_service.update_flow_docling_preset.call_args.args
    assert opts["ocr_lang"] == ["en", "ja"]
    assert opts["ocr_preset"] == "easyocr"
