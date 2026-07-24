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
        """Settings response must include agent and knowledge sections."""
        settings = await client.settings.get()

        assert settings.agent is not None
        assert settings.knowledge is not None

        knowledge = settings.knowledge
        assert knowledge.chunk_overlap is None or isinstance(knowledge.chunk_overlap, int)
        assert knowledge.table_structure is None or isinstance(knowledge.table_structure, bool)
        assert knowledge.ocr is None or isinstance(knowledge.ocr, bool)
        assert knowledge.picture_descriptions is None or isinstance(
            knowledge.picture_descriptions, bool
        )
        assert settings.agent.system_prompt is None or isinstance(
            settings.agent.system_prompt, str
        )

    @pytest.mark.asyncio
    async def test_update_settings(self, client):
        """Updating a setting must persist and be readable back."""
        current_settings = await client.settings.get()
        current_chunk_size = current_settings.knowledge.chunk_size or 1000

        result = await client.settings.update({"chunk_size": current_chunk_size})
        assert result.message is not None

        updated_settings = await client.settings.get()
        assert updated_settings.knowledge.chunk_size == current_chunk_size
