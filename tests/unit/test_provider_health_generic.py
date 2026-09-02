"""Generic LiteLLM providers must be accepted by the provider-health endpoint."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api import models as models_api
from api.provider_health import check_provider_health
from config import model_providers


@pytest.mark.asyncio
async def test_provider_health_accepts_configured_azure_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    azure = SimpleNamespace(
        api_key=None,
        endpoint=None,
        project_id=None,
    )
    providers = SimpleNamespace(
        get_provider_config=lambda provider: azure,
        credential_values=lambda provider: {
            "api_key": "azure-secret",
            "api_base": "https://example.openai.azure.com",
            "api_version": "2024-10-21",
        },
    )
    config = SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-4o-mini"),
        knowledge=SimpleNamespace(
            embedding_provider="azure",
            embedding_model="embedding-deployment",
        ),
    )
    validate = AsyncMock()
    monkeypatch.setattr("api.provider_health.get_openrag_config", lambda: config)
    monkeypatch.setattr("api.provider_health.validate_provider_setup", validate)

    response = await check_provider_health(
        provider="azure",
        embedding_model_override="embedding-deployment",
        test_completion=True,
        user=None,
    )

    assert response.status_code == 200
    assert json.loads(response.body)["provider"] == "azure"
    validate.assert_awaited_once_with(
        provider="azure",
        api_key=None,
        embedding_model="embedding-deployment",
        llm_model=None,
        endpoint=None,
        project_id=None,
        test_completion=True,
        credentials={
            "api_key": "azure-secret",
            "api_base": "https://example.openai.azure.com",
            "api_version": "2024-10-21",
        },
    )


@pytest.mark.asyncio
async def test_provider_page_catalog_contract_includes_azure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two provider-page discovery requests agree that Azure is available."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    model_providers.reload()
    try:
        providers_response = await models_api.get_model_providers(user=SimpleNamespace())
        catalog_response = await models_api.get_model_catalog(user=SimpleNamespace())
    finally:
        model_providers.reload()

    providers = json.loads(providers_response.body)["providers"]
    catalog = json.loads(catalog_response.body)["providers"]

    assert providers_response.status_code == 200
    assert catalog_response.status_code == 200
    assert "azure" in {provider["name"] for provider in providers}
    assert "azure" in {provider["key"] for provider in catalog}
