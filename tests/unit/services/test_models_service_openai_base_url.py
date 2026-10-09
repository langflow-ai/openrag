"""Coverage for the OpenAI custom base-URL override reaching model listing
(openrag issue #2060).

Before this fix, `ModelsService.get_openai_models` hardcoded
`https://api.openai.com/v1/models`, so the Settings UI's model picker (and
`update_model_registry`) always queried the real OpenAI API instead of the
configured gateway.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import services.models_service as models_service_module
from services.models_service import ModelsService

CUSTOM_BASE_URL = "http://localhost:4444/v1"


def _resp(status_code: int, json_data: dict) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = json_data
    return r


@pytest.fixture
def mock_client(monkeypatch):
    c = AsyncMock(spec=httpx.AsyncClient)
    c.__aenter__.return_value = c
    monkeypatch.setattr(models_service_module.httpx, "AsyncClient", MagicMock(return_value=c))
    return c


@pytest.mark.asyncio
async def test_get_openai_models_hits_configured_gateway(mock_client):
    mock_client.get.return_value = _resp(200, {"data": []})
    service = ModelsService()

    await service.get_openai_models("sk-test", base_url=CUSTOM_BASE_URL)

    called_url = mock_client.get.call_args.args[0]
    assert called_url == f"{CUSTOM_BASE_URL}/models"


@pytest.mark.asyncio
async def test_get_openai_models_falls_back_to_real_openai_when_unset(mock_client):
    mock_client.get.return_value = _resp(200, {"data": []})
    service = ModelsService()

    await service.get_openai_models("sk-test", base_url=None)

    called_url = mock_client.get.call_args.args[0]
    assert called_url == "https://api.openai.com/v1/models"


@pytest.mark.asyncio
async def test_get_openai_models_relaxes_classification_for_custom_gateway(mock_client):
    """A gateway serving non-OpenAI-named models must still populate both
    pickers - without this, onboarding against a custom base_url gets stuck
    on a permanently empty "Language model" dropdown (issue #2060)."""
    mock_client.get.return_value = _resp(
        200,
        {
            "data": [
                {"id": "stub-chat-model"},
                {"id": "stub-embed-model"},
            ]
        },
    )
    service = ModelsService()

    result = await service.get_openai_models(
        "sk-test", base_url=CUSTOM_BASE_URL, update_index=False
    )

    assert [m["value"] for m in result["language_models"]] == ["stub-chat-model"]
    assert [m["value"] for m in result["embedding_models"]] == ["stub-embed-model"]


@pytest.mark.asyncio
async def test_get_openai_models_keeps_strict_classification_without_base_url(
    mock_client,
):
    mock_client.get.return_value = _resp(
        200,
        {
            "data": [
                {"id": "stub-chat-model"},
                {"id": "gpt-4o"},
            ]
        },
    )
    service = ModelsService()

    result = await service.get_openai_models("sk-test", base_url=None, update_index=False)

    assert [m["value"] for m in result["language_models"]] == ["gpt-4o"]
