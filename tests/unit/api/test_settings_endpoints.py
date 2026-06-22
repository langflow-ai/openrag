"""
Unit tests for api.settings.endpoints
Validates error handling in update_docling_preset endpoint.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.settings import update_docling_preset, DoclingPresetBody
from session_manager import User


@pytest.mark.asyncio
async def test_update_docling_preset_invalid_preset_returns_400():
    """Test that an invalid preset value returns 400 status code.

    This test ensures that the HTTPException with status_code=400 raised
    for invalid presets is not masked by the broad Exception handler.
    Regression test for PR #1814 / issue #1586.
    """
    # Create a body with an invalid preset
    body = DoclingPresetBody(preset="nonexistent_preset")

    # Mock dependencies
    session_manager = AsyncMock()
    user = MagicMock(spec=User)

    # Call the endpoint and expect HTTPException with 400
    with pytest.raises(HTTPException) as exc_info:
        await update_docling_preset(body=body, session_manager=session_manager, user=user)

    # Assert it's a 400 error (not 500)
    assert exc_info.value.status_code == 400
    assert "Invalid preset" in exc_info.value.detail
    assert "nonexistent_preset" in exc_info.value.detail
