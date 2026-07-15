"""Regression test: the public v1 ingest endpoint calls upload_ingest_router
directly (not via FastAPI form parsing), so it must forward an explicit string
for every Form-defaulted param. Previously ``preview`` was omitted, leaking the
``Form("false")`` sentinel into ``preview.lower()`` and raising
``AttributeError: 'Form' object has no attribute 'lower'`` (HTTP 500).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1.documents import ingest_endpoint
from session_manager import User


@pytest.mark.asyncio
async def test_v1_ingest_forwards_preview_as_string():
    user = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")

    with patch("api.v1.documents.upload_ingest_router", new=AsyncMock()) as mock_router:
        await ingest_endpoint(
            file=[MagicMock()],
            session_id=None,
            settings=None,
            tweaks=None,
            replace_duplicates="true",
            create_filter="false",
            document_service=MagicMock(),
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=MagicMock(),
            user=user,
        )

    call_kwargs = mock_router.await_args.kwargs
    # Must be a real string so upload_ingest_router's preview.lower() works.
    assert isinstance(call_kwargs["preview"], str)
    assert call_kwargs["preview"] == "false"
