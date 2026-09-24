"""`validate_provider_setup` says what a passing validation actually exercised.

The health check erases a real-traffic failure only on evidence as strong as
that failure, so each branch has to report honestly: a deployment listing, a
key check, or a missing model is not a model call, and the LiteLLM probe's
plain completion is not a tool-calling one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api import provider_validation
from api.provider_validation import ProbeResult, validate_provider_setup


@pytest.fixture
def calls(monkeypatch):
    """Stub every probe the validator can reach, recording which one ran."""
    ran: list[str] = []

    def stub(name):
        async def probe(*_args, **_kwargs):
            ran.append(name)

        return probe

    for name in (
        "_test_litellm_provider",
        "test_lightweight_health",
        "test_embedding",
        "test_completion_with_tools",
    ):
        monkeypatch.setattr(provider_validation, name, stub(name))
    monkeypatch.setattr(provider_validation, "get_provider_enhancement", lambda _p: None)
    return ran


@pytest.mark.asyncio
async def test_a_native_tool_calling_completion_is_reported_as_one(calls):
    result = await validate_provider_setup(
        provider="openai", api_key="k", llm_model="gpt-4o", test_completion=True
    )

    assert calls == ["test_completion_with_tools"]
    assert result == ProbeResult(model_probed=True, tools_exercised=True)


@pytest.mark.asyncio
async def test_a_native_embedding_call_probes_the_model(calls):
    result = await validate_provider_setup(
        provider="openai",
        api_key="k",
        embedding_model="text-embedding-3-small",
        test_completion=True,
    )

    assert calls == ["test_embedding"]
    assert result == ProbeResult(model_probed=True)


@pytest.mark.asyncio
async def test_the_litellm_probe_calls_the_model_without_tools(monkeypatch, calls):
    """RHOAI and every other enhancement: a plain `Reply with OK.` completion."""
    monkeypatch.setattr(
        provider_validation, "get_provider_enhancement", lambda _p: SimpleNamespace()
    )
    monkeypatch.setattr("enhancements.providers.registry.runtime_kwargs_for", lambda *_a, **_k: {})

    result = await validate_provider_setup(
        provider="rhoai", llm_model="granite", test_completion=True, credentials={}
    )

    assert calls == ["_test_litellm_provider"]
    assert result == ProbeResult(model_probed=True, tools_exercised=False)


@pytest.mark.asyncio
async def test_azure_lists_deployments_and_calls_no_model(calls):
    result = await validate_provider_setup(
        provider="azure",
        api_key="k",
        endpoint="https://example.openai.azure.com",
        llm_model="my-deployment",
        test_completion=True,
    )

    assert calls == ["test_lightweight_health"]
    assert result == ProbeResult()


@pytest.mark.asyncio
async def test_no_model_means_no_call(calls):
    """Azure after #2384 leaves the model empty; nothing is probed then."""
    result = await validate_provider_setup(provider="openai", api_key="k", test_completion=True)

    assert calls == []
    assert result == ProbeResult()


@pytest.mark.asyncio
async def test_a_lightweight_check_calls_no_model(calls):
    result = await validate_provider_setup(provider="openai", api_key="k", llm_model="gpt-4o")

    assert calls == ["test_lightweight_health"]
    assert result == ProbeResult()
