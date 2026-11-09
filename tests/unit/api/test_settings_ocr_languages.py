"""OCR language settings round-trip through the settings endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.settings.endpoints import update_settings
from api.settings.models import SettingsUpdateBody
from config.config_manager import OpenRAGConfig


def _edited_config() -> OpenRAGConfig:
    config = OpenRAGConfig.from_dict({})
    config.edited = True
    return config


@pytest.mark.asyncio
async def test_update_settings_persists_ocr_languages():
    """Saving OCR languages stores them on the knowledge config."""
    current = _edited_config()
    saved = {}

    def capture(config):
        saved["config"] = config
        return True

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=current),
        patch("api.settings.endpoints.config_manager.save_config_file", side_effect=capture),
        patch("api.settings.endpoints._get_flows_service", return_value=MagicMock()),
        patch("api.settings.endpoints._update_langflow_docling_settings", new=AsyncMock()),
        patch("api.settings.endpoints.TelemetryClient.send_event", new=AsyncMock()),
        patch("api.settings.endpoints.provider_health_cache", MagicMock()),
    ):
        await update_settings(
            body=SettingsUpdateBody(ocr_languages=["en", "ja"]),
            session_manager=AsyncMock(),
            user=MagicMock(),
            models_service=MagicMock(),
            rbac=MagicMock(),
        )

    assert saved["config"].knowledge.ocr_languages == ["ja", "en"]


@pytest.mark.asyncio
async def test_docling_preset_endpoint_keeps_configured_ocr_languages():
    """The legacy preset endpoint must not wipe OCR languages from the ingest flow."""
    from api.settings import DoclingPresetBody, update_docling_preset

    current = _edited_config()
    current.knowledge.ocr_languages = ["en", "ja"]

    flows_service = MagicMock()
    flows_service.update_flow_docling_preset = AsyncMock()

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=current),
        patch("api.settings.endpoints._get_flows_service", return_value=flows_service),
        patch("services.docling_service.platform.system", return_value="Darwin"),
    ):
        await update_docling_preset(
            body=DoclingPresetBody(ocr=True),
            session_manager=AsyncMock(),
            user=MagicMock(),
        )

    _, opts = flows_service.update_flow_docling_preset.call_args.args
    assert opts["ocr_lang"] == ["ja-JP", "en-US"]
