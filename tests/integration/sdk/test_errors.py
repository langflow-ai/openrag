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

"""Tests for SDK error handling and propagation."""

import io
import os
import uuid

import pytest

from .conftest import _base_url

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestErrorHandling:
    """Verify the SDK surfaces errors correctly rather than swallowing them."""

    @pytest.mark.asyncio
    async def test_connection_refused_raises_exception(self):
        """Pointing the client at a dead port must raise a network exception, not hang."""
        from openrag_sdk import OpenRAGClient

        dead_client = OpenRAGClient(
            api_key="orag_test",
            base_url="http://localhost:19999",
            timeout=3.0,
        )
        try:
            with pytest.raises(Exception):
                await dead_client.settings.get()
        finally:
            await dead_client.close()

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation_raises_not_found(self, client):
        """Fetching a conversation with a random UUID must raise NotFoundError."""
        from openrag_sdk.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await client.chat.get(str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation_returns_false(self, client):
        """Deleting a conversation that never existed must return False."""
        result = await client.chat.delete(str(uuid.uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_invalid_settings_value_raises_error(self, client):
        """Sending an invalid settings value must raise a subclass of OpenRAGError."""
        from openrag_sdk.exceptions import OpenRAGError

        with pytest.raises(OpenRAGError):
            await client.settings.update({"chunk_size": -999999})

    @pytest.mark.asyncio
    async def test_ingest_without_file_raises_value_error(self, client):
        """Calling ingest() with neither file_path nor file must raise ValueError."""
        with pytest.raises(ValueError):
            await client.documents.ingest()

    @pytest.mark.asyncio
    async def test_ingest_file_object_without_filename_raises_value_error(self, client):
        """Providing a file object without a filename must raise ValueError."""
        with pytest.raises(ValueError):
            await client.documents.ingest(file=io.BytesIO(b"content"))
