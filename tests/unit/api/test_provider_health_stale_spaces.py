"""A vector space outlives the model that made it.

A chunk records the space it was embedded in (`provider:model`), retrieval
embeds the query once per space found in the corpus, and an `InferenceService`
redeployed under a new `--served-model-name` leaves every earlier chunk
pointing at a model that is gone. Nothing else in the health path looks at the
corpus: the *configured* model is still fine, so every probe passes and the
banner stays green while those documents quietly drop out of vector search.
These pin that it gets said instead — as a warning beside the verdict, not as a
provider failure, because the provider is serving and its setup is not what
needs fixing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api import provider_health
from api.provider_validation import ProbeResult
from services import provider_error_log

SERVED = "redhataigranite-embedding-engl"
STALE = "granite-embedding-english-r2"


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
        knowledge=SimpleNamespace(embedding_provider="rhoai", embedding_model=SERVED),
        get_llm_provider_config=lambda: SimpleNamespace(api_key="k"),
        get_embedding_provider_config=lambda: SimpleNamespace(api_key="k"),
    )


@pytest.fixture
def _healthy_probe(monkeypatch):
    """Everything the probes touch passes, so only the corpus can speak."""
    monkeypatch.setattr(provider_health, "get_openrag_config", _config)
    monkeypatch.setattr(provider_health, "is_known_provider", lambda _p: True)

    async def ok(**_kwargs):
        return ProbeResult()

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

    async def no_refresh(_provider):
        return None

    monkeypatch.setattr(provider_health, "_refresh_live_models", no_refresh)


def _served(monkeypatch, models):
    import enhancements.providers.registry as registry

    monkeypatch.setattr(registry, "live_models_for", lambda _provider, _kind: models)


def _indexed(monkeypatch, models):
    async def spaces(_provider):
        return models

    monkeypatch.setattr(provider_health, "_indexed_spaces", spaces)


def _body(response):
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_a_space_the_endpoint_no_longer_serves_is_a_warning_not_a_failure(
    monkeypatch, _healthy_probe
):
    _served(monkeypatch, (SERVED,))
    _indexed(monkeypatch, (SERVED, STALE))

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    # The provider is serving; only the corpus is out of date.
    assert response.status_code == 200
    body = _body(response)
    assert body["status"] == "healthy"
    [warning] = body["warnings"]
    assert warning["code"] == provider_health.STALE_EMBEDDING_SPACE
    assert warning["provider"] == "rhoai"
    assert warning["models"] == [STALE]
    assert warning["served"] == [SERVED]
    assert "re-ingested or deleted" in warning["message"]


@pytest.mark.asyncio
async def test_the_warning_says_search_degrades_rather_than_fails(monkeypatch, _healthy_probe):
    """Retrieval skips a space it cannot embed for; it does not fail the search."""
    _served(monkeypatch, (SERVED,))
    _indexed(monkeypatch, (STALE,))

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    message = _body(response)["warnings"][0]["message"]
    assert "keyword only" in message
    assert "will fail" not in message


@pytest.mark.asyncio
async def test_a_corpus_that_matches_what_is_served_says_nothing(monkeypatch, _healthy_probe):
    _served(monkeypatch, (SERVED,))
    _indexed(monkeypatch, (SERVED,))

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 200
    assert _body(response)["warnings"] == []


@pytest.mark.asyncio
async def test_an_unknown_listing_is_not_evidence_of_a_stale_corpus(monkeypatch, _healthy_probe):
    """An unreachable cluster must not read as every document being stale."""
    _served(monkeypatch, None)
    _indexed(monkeypatch, (STALE,))

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 200
    assert _body(response)["warnings"] == []


@pytest.mark.asyncio
async def test_an_empty_corpus_is_not_evidence_of_drift(monkeypatch, _healthy_probe):
    _served(monkeypatch, (SERVED,))
    _indexed(monkeypatch, None)

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 200
    assert _body(response)["warnings"] == []


@pytest.mark.asyncio
async def test_a_real_failure_keeps_its_own_words_and_the_warning_rides_beside_it(
    monkeypatch, _healthy_probe
):
    async def boom(**kwargs):
        if kwargs.get("embedding_model"):
            raise RuntimeError("endpoint unreachable")
        return ProbeResult()

    monkeypatch.setattr(provider_health, "validate_provider_setup", boom)
    _served(monkeypatch, (SERVED,))
    _indexed(monkeypatch, (STALE,))

    response = await provider_health.check_provider_health(test_completion=True, user=None)

    assert response.status_code == 503
    body = _body(response)
    # The failure is reported as itself, not diluted by corpus advice...
    assert body["embedding_error"] == "endpoint unreachable"
    # ...and the corpus advice is still there for when the provider recovers.
    assert body["warnings"][0]["models"] == [STALE]


# --------------------------------------------------------------------------
# Refreshing what the provider serves
# --------------------------------------------------------------------------


@pytest.fixture
def _refreshes(monkeypatch):
    """Record which providers the catalogue is asked to re-list."""
    import services.model_catalog as model_catalog

    asked: list[str | None] = []

    async def refresh(provider=None):
        asked.append(provider)

    monkeypatch.setattr(model_catalog, "refresh_live_models", refresh)
    return asked


@pytest.mark.asyncio
async def test_only_the_checked_provider_is_refreshed(monkeypatch, _refreshes):
    import enhancements.providers.registry as registry

    monkeypatch.setattr(registry, "get", lambda _p: SimpleNamespace(fetch_models=lambda _c: None))

    await provider_health._refresh_live_models("rhoai")

    assert _refreshes == ["rhoai"]


@pytest.mark.asyncio
async def test_a_provider_that_cannot_list_its_models_is_not_refreshed(monkeypatch, _refreshes):
    """openai and friends have no enhancement: nothing to re-list, no call made."""
    import enhancements.providers.registry as registry

    monkeypatch.setattr(registry, "get", lambda _p: None)
    await provider_health._refresh_live_models("openai")

    monkeypatch.setattr(registry, "get", lambda _p: SimpleNamespace())
    await provider_health._refresh_live_models("listless")

    assert _refreshes == []


@pytest.mark.asyncio
async def test_a_slow_cluster_cannot_stall_the_health_check(monkeypatch):
    import asyncio

    import enhancements.providers.registry as registry
    import services.model_catalog as model_catalog

    monkeypatch.setattr(registry, "get", lambda _p: SimpleNamespace(fetch_models=lambda _c: None))

    async def hang(provider=None):
        await asyncio.sleep(60)

    monkeypatch.setattr(model_catalog, "refresh_live_models", hang)
    monkeypatch.setattr(provider_health, "_MODEL_REFRESH_TIMEOUT_SECONDS", 0.01)

    # Returns (quietly) instead of raising or waiting out the listing.
    await asyncio.wait_for(provider_health._refresh_live_models("rhoai"), timeout=1)


@pytest.mark.asyncio
async def test_the_health_check_refreshes_the_embedding_provider(monkeypatch, _healthy_probe):
    asked: list[str] = []

    async def refresh(provider):
        asked.append(provider)

    monkeypatch.setattr(provider_health, "_refresh_live_models", refresh)
    _served(monkeypatch, None)

    await provider_health.check_provider_health(test_completion=True, user=None)

    assert asked == ["rhoai"]


# --------------------------------------------------------------------------
# Reading the corpus
# --------------------------------------------------------------------------


def _aggregation(*space_ids):
    return {
        "aggregations": {
            "embedding_spaces": {
                "buckets": [{"key": {"space_id": space_id}} for space_id in space_ids]
            }
        }
    }


@pytest.fixture
def _opensearch(monkeypatch):
    """Swap the admin client for one that replays a canned aggregation."""

    def install(result, *, fails=False):
        class _Client:
            async def search(self, **_kwargs):
                if fails:
                    raise RuntimeError("opensearch is down")
                return result

        monkeypatch.setattr(
            "config.settings.clients", SimpleNamespace(opensearch=_Client()), raising=False
        )
        monkeypatch.setattr("config.settings.get_index_name", lambda: "documents", raising=False)

    return install


def _page(*space_ids, after=None, **extra):
    """One composite-aggregation page; `after` is the cursor it hands back."""
    result = _aggregation(*space_ids)
    if after is not None:
        result["aggregations"]["embedding_spaces"]["after_key"] = {"space_id": after}
    result.update(extra)
    return result


@pytest.fixture
def _paged_opensearch(monkeypatch):
    """An admin client that serves `pages` in order and records each request."""

    def install(*pages):
        requests: list[dict] = []
        remaining = list(pages)

        class _Client:
            async def search(self, **kwargs):
                requests.append(kwargs)
                return remaining.pop(0)

        monkeypatch.setattr(
            "config.settings.clients", SimpleNamespace(opensearch=_Client()), raising=False
        )
        monkeypatch.setattr("config.settings.get_index_name", lambda: "documents", raising=False)
        return requests

    return install


def _after(request):
    return request["body"]["aggs"]["embedding_spaces"]["composite"].get("after")


@pytest.mark.asyncio
async def test_indexed_spaces_follows_the_cursor_past_the_first_page(
    monkeypatch, _paged_opensearch
):
    """A stale space on page two is still a stale space."""
    monkeypatch.setattr(provider_health, "_EMBEDDING_SPACE_PAGE_SIZE", 2)
    requests = _paged_opensearch(
        _page("openai:text-embedding-3-small", f"rhoai:{SERVED}", after=f"rhoai:{SERVED}"),
        _page(f"rhoai:{STALE}"),
    )

    assert await provider_health._indexed_spaces("rhoai") == (SERVED, STALE)
    assert [_after(request) for request in requests] == [None, {"space_id": f"rhoai:{SERVED}"}]


@pytest.mark.asyncio
async def test_indexed_spaces_stops_at_a_short_page(_paged_opensearch):
    """The last page still carries an `after_key`; following it is a wasted read."""
    requests = _paged_opensearch(_page(f"rhoai:{SERVED}", after=f"rhoai:{SERVED}"))

    assert await provider_health._indexed_spaces("rhoai") == (SERVED,)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_indexed_spaces_refuses_partial_results(_paged_opensearch):
    """A failed shard must raise, not hand back fewer buckets as if complete."""
    requests = _paged_opensearch(_page(f"rhoai:{SERVED}"))

    await provider_health._indexed_spaces("rhoai")

    assert requests[0]["params"] == {"allow_partial_search_results": "false"}


@pytest.mark.asyncio
async def test_indexed_spaces_is_unknown_when_the_read_timed_out(_paged_opensearch):
    _paged_opensearch(_page(f"rhoai:{SERVED}", timed_out=True))

    assert await provider_health._indexed_spaces("rhoai") is None


@pytest.mark.asyncio
async def test_indexed_spaces_is_unknown_past_the_page_limit(monkeypatch, _paged_opensearch):
    """Running out of pages before the cursor does is not knowing, not a full list."""
    monkeypatch.setattr(provider_health, "_EMBEDDING_SPACE_PAGE_SIZE", 1)
    monkeypatch.setattr(provider_health, "_EMBEDDING_SPACE_MAX_PAGES", 2)
    _paged_opensearch(
        _page(f"rhoai:{SERVED}", after=f"rhoai:{SERVED}"),
        _page(f"rhoai:{STALE}", after=f"rhoai:{STALE}"),
    )

    assert await provider_health._indexed_spaces("rhoai") is None


@pytest.mark.asyncio
async def test_indexed_spaces_returns_this_providers_models(_opensearch):
    _opensearch(_aggregation(f"rhoai:{SERVED}", f"rhoai:{STALE}"))

    assert await provider_health._indexed_spaces("rhoai") == (SERVED, STALE)


@pytest.mark.asyncio
async def test_indexed_spaces_ignores_other_providers(_opensearch):
    """A corpus can hold spaces from a provider that is not the one selected."""
    _opensearch(_aggregation("openai:text-embedding-3-small", f"rhoai:{SERVED}"))

    assert await provider_health._indexed_spaces("rhoai") == (SERVED,)


@pytest.mark.asyncio
async def test_indexed_spaces_is_unknown_when_opensearch_cannot_answer(_opensearch):
    _opensearch(None, fails=True)

    assert await provider_health._indexed_spaces("rhoai") is None


@pytest.mark.asyncio
async def test_indexed_spaces_is_unknown_when_nothing_is_indexed(_opensearch):
    _opensearch(_aggregation())

    assert await provider_health._indexed_spaces("rhoai") is None
