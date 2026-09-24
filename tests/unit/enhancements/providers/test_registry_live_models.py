"""What a provider says it serves, read back from its own cache.

`live_models_for` is the half of model-drift detection that must never guess:
a provider that cannot list itself, or has not listed itself yet, is *unknown*,
and a caller that treats unknown as "serves nothing" would tell an operator to
change a setting that was right all along.
"""

from __future__ import annotations

from types import SimpleNamespace

from enhancements.providers import registry


class _Listing(SimpleNamespace):
    """Stands in for `ClusterModels`: one attribute per endpoint."""


def _enhancement(monkeypatch, module):
    monkeypatch.setitem(registry._ENHANCEMENTS, "probe", module)


def test_a_provider_with_no_enhancement_is_unknown():
    assert registry.live_models_for("openai", "chat") is None
    assert registry.live_models_for("", "chat") is None


def test_an_enhancement_that_cannot_list_its_models_is_unknown(monkeypatch):
    _enhancement(monkeypatch, SimpleNamespace(PROVIDER_KEY="probe"))

    assert registry.live_models_for("probe", "chat") is None


def test_nothing_cached_yet_is_unknown(monkeypatch):
    _enhancement(monkeypatch, SimpleNamespace(cached_models=lambda: None))

    assert registry.live_models_for("probe", "embedding") is None


def test_a_cached_listing_is_split_by_endpoint(monkeypatch):
    _enhancement(
        monkeypatch,
        SimpleNamespace(
            cached_models=lambda: _Listing(
                chat=("gpt-oss-120b",), embedding=("redhataigranite-embedding-engl",)
            )
        ),
    )

    assert registry.live_models_for("probe", "chat") == ("gpt-oss-120b",)
    assert registry.live_models_for("probe", "embedding") == ("redhataigranite-embedding-engl",)


def test_one_endpoint_can_be_known_while_the_other_is_not(monkeypatch):
    """A rolling embedding deployment must not make the chat list unknown too."""
    _enhancement(
        monkeypatch,
        SimpleNamespace(cached_models=lambda: _Listing(chat=("gpt-oss-120b",), embedding=None)),
    )

    assert registry.live_models_for("probe", "chat") == ("gpt-oss-120b",)
    assert registry.live_models_for("probe", "embedding") is None


def test_the_provider_key_is_matched_the_way_it_is_stored(monkeypatch):
    _enhancement(
        monkeypatch,
        SimpleNamespace(cached_models=lambda: _Listing(chat=("m",), embedding=("m",))),
    )

    assert registry.live_models_for("  PROBE ", "chat") == ("m",)


def test_a_listing_that_raises_is_unknown_rather_than_fatal(monkeypatch):
    def boom():
        raise RuntimeError("cache exploded")

    _enhancement(monkeypatch, SimpleNamespace(cached_models=boom))

    assert registry.live_models_for("probe", "chat") is None
