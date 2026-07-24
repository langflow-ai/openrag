"""Tests for authentication and API key behaviour."""

import os

import httpx
import pytest

from .conftest import _base_url

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestAuth:
    """Test authentication and API key behaviour."""

    def test_missing_api_key_and_extra_headers_raises_at_construction(self):
        """Client must raise AuthenticationError immediately when neither api_key
        nor extra_headers are supplied (and no OPENRAG_API_KEY env var is set)."""
        from openrag_sdk import OpenRAGClient
        from openrag_sdk.exceptions import AuthenticationError

        env_backup = os.environ.pop("OPENRAG_API_KEY", None)
        try:
            with pytest.raises(AuthenticationError) as exc_info:
                OpenRAGClient()
            assert "API key or extra headers are required" in str(exc_info.value)
        finally:
            if env_backup is not None:
                os.environ["OPENRAG_API_KEY"] = env_backup

    @pytest.mark.asyncio
    async def test_extra_headers_alone_satisfies_auth_check(self):
        """Client must not raise when extra_headers are provided without an api_key,
        and must actually attach those headers to real outgoing requests.

        This covers the IBM auth mode where X-Username / X-Api-Key are passed via
        extra_headers instead of the OPENRAG_API_KEY env var or api_key argument.
        A real request is made here to prove the headers are sent end-to-end
        rather than merely accepted at construction time. Whether the server
        authenticates the request successfully depends on IBM_AUTH_ENABLED
        being set on the target instance (off by default for a standard
        `make test-sdk` run), so both a successful response and a clean 401
        (a server-side rejection, which still proves the request — and its
        headers — reached the server) are accepted outcomes.
        """
        from openrag_sdk import OpenRAGClient
        from openrag_sdk.exceptions import AuthenticationError

        env_backup = os.environ.pop("OPENRAG_API_KEY", None)
        captured_headers: dict[str, str] = {}

        async def capture_request(request: httpx.Request) -> None:
            captured_headers.update(request.headers)

        try:
            async with httpx.AsyncClient(
                timeout=30.0, event_hooks={"request": [capture_request]}
            ) as http_client:
                ibm_client = OpenRAGClient(
                    extra_headers={"X-Username": "testuser", "X-Api-Key": "ibm-key"},
                    base_url=_base_url,
                    http_client=http_client,
                )
                assert ibm_client is not None

                try:
                    settings = await ibm_client.settings.get()
                    assert settings.agent is not None
                except AuthenticationError as e:
                    assert e.status_code == 401
        finally:
            if env_backup is not None:
                os.environ["OPENRAG_API_KEY"] = env_backup

        assert captured_headers.get("X-Username") == "testuser"
        assert captured_headers.get("X-Api-Key") == "ibm-key"

    def test_env_var_api_key_satisfies_auth_check(self):
        """Client must not raise when only the OPENRAG_API_KEY env var is set."""
        from openrag_sdk import OpenRAGClient

        env_backup = os.environ.pop("OPENRAG_API_KEY", None)
        try:
            os.environ["OPENRAG_API_KEY"] = "orag_env_var_key"
            client = OpenRAGClient(base_url=_base_url)
            assert client is not None
        finally:
            del os.environ["OPENRAG_API_KEY"]
            if env_backup is not None:
                os.environ["OPENRAG_API_KEY"] = env_backup

    def test_explicit_api_key_takes_precedence_over_env_var(self):
        """Explicit api_key argument overrides the OPENRAG_API_KEY env var."""
        from openrag_sdk import OpenRAGClient

        env_backup = os.environ.pop("OPENRAG_API_KEY", None)
        try:
            os.environ["OPENRAG_API_KEY"] = "orag_env_var_key"
            client = OpenRAGClient(api_key="orag_explicit_key", base_url=_base_url)
            assert client._api_key == "orag_explicit_key"
        finally:
            del os.environ["OPENRAG_API_KEY"]
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
