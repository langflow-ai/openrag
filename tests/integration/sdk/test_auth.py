"""Tests for authentication and API key behaviour."""

import os

import pytest

from .conftest import _base_url

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestAuth:
    """Test authentication and API key behaviour."""

    def test_missing_api_key_raises_at_construction(self):
        """Client must raise AuthenticationError immediately if no api_key is given."""
        from openrag_sdk import OpenRAGClient
        from openrag_sdk.exceptions import AuthenticationError

        env_backup = os.environ.pop("OPENRAG_API_KEY", None)
        try:
            with pytest.raises(AuthenticationError):
                OpenRAGClient()
        finally:
            if env_backup is not None:
                os.environ["OPENRAG_API_KEY"] = env_backup

    @pytest.mark.asyncio
    async def test_invalid_api_key_raises_auth_error(self):
        """Requests with a bogus key must raise AuthenticationError (401/403)."""
        from openrag_sdk import OpenRAGClient
        from openrag_sdk.exceptions import AuthenticationError

        bad_client = OpenRAGClient(api_key="orag_invalid_key_for_testing", base_url=_base_url)
        try:
            with pytest.raises(AuthenticationError) as exc_info:
                await bad_client.settings.get()
            assert exc_info.value.status_code in (401, 403)
        finally:
            await bad_client.close()

    @pytest.mark.asyncio
    async def test_revoked_api_key_raises_auth_error(self):
        """A well-formed but non-existent key must be rejected."""
        from openrag_sdk import OpenRAGClient
        from openrag_sdk.exceptions import AuthenticationError

        fake_client = OpenRAGClient(
            api_key="orag_0000000000000000000000000000000000000000",
            base_url=_base_url,
        )
        try:
            with pytest.raises(AuthenticationError):
                await fake_client.chat.list()
        finally:
            await fake_client.close()
