"""Regression test: onboarding must mark env-var/IAM-role Bedrock as
`configured` when it's chosen as the embedding provider.

Bedrock is commonly configured purely via env vars/IAM role (BEDROCK_REGION,
with no explicit access keys - see config_manager.py's env-override logic
and `providers.bedrock`'s docstring). Unlike openai/watsonx/ollama, nothing
in onboarding() ever flipped `providers.bedrock.configured` to True for this
case, because there was no `elif embedding_provider == "bedrock"` branch in
the "Mark providers as configured" block. Combined with
`_has_other_configured_provider` never checking Bedrock, this meant Bedrock
was silently treated as "not really configured" everywhere despite being
the live, working embedding provider.
"""

from types import SimpleNamespace

import pytest

import api.settings as settings_api
import api.settings.endpoints as settings_endpoints
from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    BedrockConfig,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)


def _make_config_with_env_bedrock(region: str) -> OpenRAGConfig:
    """A config as it looks right after config_manager applies
    BEDROCK_REGION's env override: region populated, `configured` still
    False because the env-override path bypasses set_credentials()'s
    `configured = bool(region)` bridge."""
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            ollama=OllamaConfig(),
            watsonx=WatsonXConfig(),
            bedrock=BedrockConfig(region=region, configured=False),
        ),
        knowledge=KnowledgeConfig(embedding_model="", embedding_provider=""),
        agent=AgentConfig(llm_model="", llm_provider="openai"),
        onboarding=OnboardingState(),
        edited=False,
    )


@pytest.fixture(autouse=True)
def _stub_onboarding_side_effects(monkeypatch):
    """Neutralize everything past the config-mutation section this test
    cares about: Langflow readiness/sync and OpenSearch index setup are I/O
    this regression test isn't about."""

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(settings_endpoints, "wait_for_langflow", _async_noop, raising=True)
    monkeypatch.setattr(
        settings_endpoints, "_update_langflow_global_variables", _async_noop, raising=True
    )
    monkeypatch.setattr(settings_endpoints, "_update_mcp_server_urls", _async_noop, raising=True)
    monkeypatch.setattr(
        settings_endpoints, "_update_langflow_model_values", _async_noop, raising=True
    )
    monkeypatch.setattr(settings_endpoints.TelemetryClient, "send_event", _async_noop, raising=True)
    monkeypatch.setattr(settings_endpoints.config_manager, "save_config_file", lambda cfg: True)
    # Provider validation (test_completion=True) is Bug 4's concern, covered
    # in tests/unit/api/test_provider_validation_bedrock.py - stub it out
    # here so this test stays focused on the "Mark providers as configured"
    # step, and doesn't depend on the real global config_manager singleton
    # `_test_bedrock_lightweight_health`'s no-credentials fallback reads.
    monkeypatch.setattr(settings_endpoints, "validate_provider_setup", _async_noop, raising=True)
    # Sample-data ingestion is unrelated I/O this test's fake service
    # objects can't support; keep this test focused on the "configured"
    # flag regardless of the environment's INGEST_SAMPLE_DATA setting.
    monkeypatch.setattr(settings_endpoints, "INGEST_SAMPLE_DATA", False, raising=True)

    import main

    monkeypatch.setattr(main, "init_index", _async_noop, raising=True)
    monkeypatch.setattr(
        settings_endpoints.clients,
        "create_index_admin_opensearch_client",
        lambda *a, **k: object(),
        raising=True,
    )


@pytest.mark.asyncio
async def test_onboarding_marks_iam_role_bedrock_configured(monkeypatch):
    """IAM-role deployment: only BEDROCK_REGION is set, no explicit keys."""
    config = _make_config_with_env_bedrock(region="eu-central-1")
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)

    response = await settings_api.onboarding(
        settings_api.OnboardingBody(
            embedding_provider="bedrock", embedding_model="cohere.embed-multilingual-v3"
        ),
        flows_service=SimpleNamespace(),
        session_manager=object(),
        document_service=object(),
        models_service=object(),
        task_service=object(),
        langflow_file_service=object(),
        knowledge_filter_service=object(),
        user=None,
    )

    assert not hasattr(response, "status_code") or response.status_code not in (400, 500, 503)
    assert config.providers.bedrock.configured is True


@pytest.mark.asyncio
async def test_onboarding_does_not_mark_bedrock_configured_without_region(monkeypatch):
    """No region at all (neither env var nor explicit credentials) - nothing
    to mark as configured."""
    config = _make_config_with_env_bedrock(region="")
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)

    await settings_api.onboarding(
        settings_api.OnboardingBody(
            embedding_provider="bedrock", embedding_model="cohere.embed-multilingual-v3"
        ),
        flows_service=SimpleNamespace(),
        session_manager=object(),
        document_service=object(),
        models_service=object(),
        task_service=object(),
        langflow_file_service=object(),
        knowledge_filter_service=object(),
        user=None,
    )

    assert config.providers.bedrock.configured is False
