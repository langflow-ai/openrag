"""Tests for SDK error handling and propagation."""

import io
import os
import uuid

import httpx
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
        from bomarag_sdk import BomaRAGClient

        dead_client = BomaRAGClient(
            api_key="orag_test",
            base_url="http://localhost:19999",
            timeout=3.0,
        )
        try:
            with pytest.raises(Exception):  # noqa: B017 - any network exception is acceptable here
                await dead_client.settings.get()
        finally:
            await dead_client.close()

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation_raises_not_found(self, client):
        """Fetching a conversation with a random UUID must raise NotFoundError."""
        from bomarag_sdk.exceptions import NotFoundError

        with pytest.raises(NotFoundError) as exc_info:
            await client.chat.get(str(uuid.uuid4()))
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation_returns_false(self, client):
        """Deleting a conversation that never existed must return False."""
        result = await client.chat.delete(str(uuid.uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_invalid_settings_value_raises_error(self, client):
        """Sending an invalid settings value must raise a subclass of BomaRAGError."""
        from bomarag_sdk.exceptions import BomaRAGError

        with pytest.raises(BomaRAGError):
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

    @pytest.mark.asyncio
    async def test_reiterating_consumed_stream_raises_runtime_error(self, client):
        """Iterating a ChatStream a second time after full consumption must raise RuntimeError."""
        chat_id = None
        async with client.chat.stream(message="Say one word.") as stream:
            async for _ in stream:
                pass
            chat_id = stream.chat_id

        try:
            with pytest.raises(RuntimeError):
                async for _ in stream:
                    pass
        finally:
            if chat_id:
                await client.chat.delete(chat_id)

    @pytest.mark.asyncio
    async def test_close_does_not_close_external_http_client(self):
        """The SDK must not close a caller-supplied httpx.AsyncClient on client.close()."""
        from bomarag_sdk import BomaRAGClient

        ext_client = httpx.AsyncClient()
        try:
            sdk_client = BomaRAGClient(
                api_key="orag_test", base_url=_base_url, http_client=ext_client
            )
            await sdk_client.close()
            assert not ext_client.is_closed
        finally:
            await ext_client.aclose()

    @pytest.mark.asyncio
    async def test_client_closed_after_context_manager_exit(self):
        """An SDK-owned http client is closed on __aexit__; later calls must fail."""
        from bomarag_sdk import BomaRAGClient

        async with BomaRAGClient(api_key="orag_test", base_url=_base_url) as c:
            pass

        with pytest.raises(RuntimeError):
            await c.settings.get()
