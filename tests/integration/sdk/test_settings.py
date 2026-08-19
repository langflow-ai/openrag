"""Tests for the settings endpoint."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestSettings:
    """Test settings get and update operations."""

    @pytest.mark.asyncio
    async def test_get_settings(self, client):
        """Settings response must include agent, knowledge, and archiving sections."""
        settings = await client.settings.get()

        assert settings.agent is not None
        assert settings.knowledge is not None
        assert isinstance(settings.archiving.available, bool)
        assert isinstance(settings.archiving.enabled, bool)

        knowledge = settings.knowledge
        assert knowledge.chunk_overlap is None or isinstance(knowledge.chunk_overlap, int)
        assert knowledge.table_structure is None or isinstance(knowledge.table_structure, bool)
        assert knowledge.ocr is None or isinstance(knowledge.ocr, bool)
        assert knowledge.picture_descriptions is None or isinstance(
            knowledge.picture_descriptions, bool
        )
        assert settings.agent.system_prompt is None or isinstance(settings.agent.system_prompt, str)

    @pytest.mark.asyncio
    async def test_update_settings(self, client):
        """Updating a setting must persist and be readable back."""
        current_settings = await client.settings.get()
        current_chunk_size = current_settings.knowledge.chunk_size or 1000

        result = await client.settings.update({"chunk_size": current_chunk_size})
        assert result.message is not None

        updated_settings = await client.settings.get()
        assert updated_settings.knowledge.chunk_size == current_chunk_size

        if current_settings.archiving.available:
            original_archive_sources_enabled = current_settings.archiving.enabled
            requested_archive_sources_enabled = not original_archive_sources_enabled
            try:
                await client.settings.update(
                    {"archive_sources_enabled": requested_archive_sources_enabled}
                )
                updated_settings = await client.settings.get()
                assert updated_settings.archiving.enabled is requested_archive_sources_enabled
            finally:
                await client.settings.update(
                    {"archive_sources_enabled": original_archive_sources_enabled}
                )
