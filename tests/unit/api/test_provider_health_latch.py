"""The health banner has to be able to clear itself.

`provider_error_log` is erased by the next call to a provider that succeeds,
and until this was wired up the only such call was chat traffic. One failed
turn latched the banner, the frontend then polled every 5s with
`test_completion` while it stayed latched, and a provider that was
demonstrably serving kept being reported broken — offering "Fix Setup" for a
setup that had just passed its own check — until the entry went stale a
quarter of an hour later.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api import provider_health
from services import provider_error_log


@pytest.fixture(autouse=True)
def _clean():
    provider_error_log.clear()
    yield
    provider_error_log.clear()


def _config():
    providers = SimpleNamespace(
        credential_values=lambda *_a, **_k: {},
        stored_credentials=lambda *_a, **_k: {},
        get_provider_config=lambda *_a, **_k: SimpleNamespace(api_key="k"),
    )
    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_provider="rhoai", llm_model="gpt-oss-120b"),
        knowledge=SimpleNamespace(embedding_provider="rhoai", embedding_model="granite-embedding"),
        get_llm_provider_config=lambda: SimpleNamespace(api_key="k"),
        get_embedding_provider_config=lambda: SimpleNamespace(api_key="k"),
    )


@pytest.fixture
def _healthy_probe(monkeypatch):
    """A provider whose probes all pass, with the caches out of the way."""
    monkeypatch.setattr(provider_health, "get_openrag_config", _config)
    monkeypatch.setattr(provider_health, "is_known_provider", lambda _p: True)

    async def ok(**_kwargs):
        return None

    monkeypatch.setattr(provider_health, "validate_provider_setup", ok)
    monkeypatch.setattr(provider_health.provider_health_cache, "cache_key", lambda **_k: "key")
    monkeypatch.setattr(provider_health.provider_health_cache, "get", lambda _k: None)
    monkeypatch.setattr(
        provider_health.provider_health_cache, "set_and_release", lambda *_a, **_k: None
    )
    monkeypatch.setattr(provider_health.provider_health_cache, "release_error", lambda *_a: None)

    async def acquire(_key):
        return True

    monkeypatch.setattr(provider_health.provider_health_cache, "acquire", acquire)


@pytest.mark.asyncio
async def test_a_passing_completion_probe_clears_a_latched_chat_failure(_healthy_probe):
    provider_error_log.record_failure("rhoai", "chat", "tool_calls are not iterable")

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 200
    assert provider_error_log.latest_failure("rhoai", "chat") is None


@pytest.mark.asyncio
async def test_a_passing_completion_probe_clears_a_latched_embedding_failure(_healthy_probe):
    provider_error_log.record_failure("rhoai", "embedding", "embeddings fell over")

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 200
    assert provider_error_log.latest_failure("rhoai", "embedding") is None


@pytest.mark.asyncio
async def test_a_model_free_check_proves_too_little_to_clear_anything(_healthy_probe):
    """Without a completion there is no evidence the provider can serve a call."""
    provider_error_log.record_failure("rhoai", "chat", "tool_calls are not iterable")

    response = await provider_health.check_provider_health(test_completion=False, user=None)

    assert response.status_code == 503
    assert provider_error_log.latest_failure("rhoai", "chat") == "tool_calls are not iterable"


@pytest.mark.asyncio
async def test_a_failing_probe_leaves_the_recorded_failure_in_place(monkeypatch, _healthy_probe):
    """A provider that is genuinely broken keeps saying so, in its own words."""

    async def boom(**kwargs):
        if kwargs.get("llm_model"):
            raise RuntimeError("endpoint unreachable")

    monkeypatch.setattr(provider_health, "validate_provider_setup", boom)
    provider_error_log.record_failure("rhoai", "chat", "the real traffic failure")

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 503
    # A real call still beats a probe when both have something to say.
    assert provider_error_log.latest_failure("rhoai", "chat") == "the real traffic failure"
