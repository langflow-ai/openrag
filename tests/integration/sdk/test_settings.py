# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

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

    @pytest.mark.asyncio
    async def test_update_settings(self, client):
        """Updating a setting must persist and be readable back."""
        current_settings = await client.settings.get()
        current_chunk_size = current_settings.knowledge.chunk_size or 1000

        result = await client.settings.update({"chunk_size": current_chunk_size})
        assert result.message is not None

        updated_settings = await client.settings.get()
        assert updated_settings.knowledge.chunk_size == current_chunk_size
