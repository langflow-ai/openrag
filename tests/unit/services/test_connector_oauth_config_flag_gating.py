"""The workspace OAuth connector credential override cache must never surface
overrides — even ones already loaded into the in-process cache — while the
OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED feature flag is off."""

import pytest

from services import connector_oauth_config_service as svc


@pytest.fixture(autouse=True)
def _reset_cache():
    original = svc._CACHE
    yield
    svc._CACHE = original


def test_cached_getters_return_none_when_flag_disabled(monkeypatch):
    monkeypatch.delenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", raising=False)
    svc._CACHE = {"google_drive": {"client_id": "abc", "client_secret": "shh"}}

    assert svc.get_cached_client_id("google_drive") is None
    assert svc.get_cached_client_secret("google_drive") is None


def test_cached_getters_return_values_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", "true")
    svc._CACHE = {"google_drive": {"client_id": "abc", "client_secret": "shh"}}

    assert svc.get_cached_client_id("google_drive") == "abc"
    assert svc.get_cached_client_secret("google_drive") == "shh"


@pytest.mark.asyncio
async def test_warm_cache_no_ops_when_flag_disabled(monkeypatch):
    monkeypatch.delenv("OPENRAG_WORKSPACE_OAUTH_OVERRIDES_ENABLED", raising=False)
    svc._CACHE = None

    called = False

    def _session_factory():
        nonlocal called
        called = True
        raise AssertionError("warm_cache should not touch the DB when disabled")

    await svc.warm_cache(_session_factory)

    assert called is False
    assert svc._CACHE == {}
