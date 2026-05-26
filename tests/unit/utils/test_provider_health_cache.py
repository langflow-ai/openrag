"""Unit tests for ``utils.provider_health_cache``."""

import time

import pytest

from utils import provider_health_cache
from utils.provider_health_cache import TTLCache, cache_key


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Each test starts with an empty cache and is isolated from siblings."""
    provider_health_cache.invalidate()
    yield
    provider_health_cache.invalidate()


def _key(**overrides):
    base = dict(
        provider="watsonx",
        embedding_provider="watsonx",
        test_completion=False,
        llm_model="ibm/granite-3-8b-instruct",
        embedding_model="ibm/slate-125m-english-rtrvr-v2",
        endpoint="https://us-south.ml.cloud.ibm.com",
        project_id="proj-abc",
        api_key="key-1",
        embedding_api_key="key-1",
        embedding_endpoint="https://us-south.ml.cloud.ibm.com",
        embedding_project_id="proj-abc",
    )
    base.update(overrides)
    return cache_key(**base)


def test_get_returns_none_on_miss():
    assert provider_health_cache.get(_key()) is None


def test_set_then_get_round_trips_payload():
    key = _key()
    payload = {"status": "healthy", "llm_provider": "watsonx"}
    provider_health_cache.set_(key, payload)

    assert provider_health_cache.get(key) == payload


def test_invalidate_clears_all_entries():
    provider_health_cache.set_(_key(api_key="a"), {"ok": True})
    provider_health_cache.set_(_key(api_key="b"), {"ok": True})

    provider_health_cache.invalidate()

    assert provider_health_cache.get(_key(api_key="a")) is None
    assert provider_health_cache.get(_key(api_key="b")) is None


@pytest.mark.parametrize(
    "field,a,b",
    [
        ("provider", "watsonx", "openai"),
        ("embedding_provider", "watsonx", "openai"),
        ("test_completion", False, True),
        ("llm_model", "ibm/granite-3-8b-instruct", "ibm/granite-3-2b-instruct"),
        ("embedding_model", "ibm/slate-125m-english-rtrvr-v2", "ibm/slate-30m-english-rtrvr-v2"),
        ("endpoint", "https://us-south.ml.cloud.ibm.com", "https://eu-de.ml.cloud.ibm.com"),
        ("project_id", "proj-abc", "proj-xyz"),
        ("api_key", "key-1", "key-2"),
        (
            "embedding_endpoint",
            "https://us-south.ml.cloud.ibm.com",
            "https://eu-de.ml.cloud.ibm.com",
        ),
        ("embedding_project_id", "proj-abc", "proj-xyz"),
        ("embedding_api_key", "key-1", "key-2"),
    ],
)
def test_cache_key_differs_when_any_field_changes(field, a, b):
    assert _key(**{field: a}) != _key(**{field: b})


def test_cache_key_stable_for_identical_inputs():
    assert _key() == _key()


def test_cache_key_does_not_leak_api_key_in_plaintext():
    key = _key(api_key="super-secret-token-12345")
    # The key is BLAKE2b hex, so the raw api_key must not appear anywhere in it.
    assert "super-secret" not in key
    assert "token-12345" not in key


def test_cache_entries_expire_after_ttl(monkeypatch):
    # Replace the module-level cache with a 1-second TTL so we don't sleep 10s.
    monkeypatch.setattr(
        provider_health_cache,
        "_HEALTH_CACHE",
        TTLCache(maxsize=64, ttl=1),
    )

    key = _key()
    provider_health_cache.set_(key, {"status": "healthy"})
    assert provider_health_cache.get(key) is not None

    time.sleep(1.2)
    assert provider_health_cache.get(key) is None
