"""
Unit tests for api.settings.endpoints
Validates error handling in update_docling_preset endpoint.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.settings import DoclingPresetBody, update_docling_preset
from api.settings.models import (
    AssistantMessage,
    OnboardingBody,
    OnboardingFunctionCall,
    SettingsUpdateBody,
)
from session_manager import User


@pytest.mark.asyncio
async def test_update_docling_preset_invalid_preset_returns_400():
    """Test that an invalid preset value returns 400 status code.

    This test ensures that the HTTPException with status_code=400 raised
    for invalid presets is not masked by the broad Exception handler.
    Regression test for issue #1586.
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


def test_assistant_message_citation_serialization():
    """Test AssistantMessage model citation parsing with text and metadata."""
    payload = {
        "role": "assistant",
        "content": "Here is the response [1]",
        "timestamp": "2026-07-27T00:00:00.000Z",
        "functionCalls": [
            {
                "name": "search_docs",
                "status": "completed",
                "result": [
                    {
                        "chunk_id": "chunk-123",
                        "filename": "doc.pdf",
                        "page": 2,
                        "score": 0.95,
                        "text": "Extracted chunk text",
                        "embedding_model": "text-embedding-3-small",
                        "parser": "Docling",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "source_url": "https://example.com/doc.pdf",
                        "metadata": {"custom_key": "val"},
                        "data": {
                            "file_path": "/path/to/doc.pdf",
                            "page": 2,
                            "score": 0.95,
                            "text": "Extracted chunk text",
                            "embedding_model": "text-embedding-3-small",
                            "parser": "Docling",
                            "chunk_size": 512,
                            "chunk_overlap": 64,
                        },
                    }
                ],
            }
        ],
    }

    msg = AssistantMessage(**payload)
    assert msg.functionCalls is not None
    assert len(msg.functionCalls) == 1
    fc = msg.functionCalls[0]
    assert isinstance(fc, OnboardingFunctionCall)
    assert fc.result is not None
    result = fc.result[0]
    assert result.text == "Extracted chunk text"
    assert result.embedding_model == "text-embedding-3-small"
    assert result.parser == "Docling"
    assert result.chunk_size == 512
    assert result.chunk_overlap == 64
    assert result.source_url == "https://example.com/doc.pdf"
    assert result.metadata == {"custom_key": "val"}
    assert result.data is not None
    assert result.data.text == "Extracted chunk text"


def test_settings_models_accept_arbitrary_provider_credentials():
    credentials = {
        "gemini": {
            "api_key": "secret",
            "vertex_project": "project-1",
            "vertex_location": "us-central1",
        }
    }

    settings = SettingsUpdateBody(
        llm_provider="gemini",
        llm_model="gemini-2.5-pro",
        provider_credentials=credentials,
    )
    onboarding = OnboardingBody(
        llm_provider="gemini",
        llm_model="gemini-2.5-pro",
        provider_credentials=credentials,
    )

    assert settings.provider_credentials == credentials
    assert onboarding.provider_credentials == credentials


def test_custom_provider_payload_keeps_legacy_openai_secret():
    from api.settings.endpoints import _custom_providers_for_settings
    from config.config_manager import BomaRAGConfig

    config = BomaRAGConfig.from_dict({})
    config.providers.openai.api_key = "sk-test"
    config.providers.openai.configured = True
    config.providers.set_credentials("openai", {"organization": "org-1"})

    payload = _custom_providers_for_settings(config)
    assert payload["openai"].secret_fields == ["api_key"]
    assert payload["openai"].credential_values["organization"] == "org-1"
