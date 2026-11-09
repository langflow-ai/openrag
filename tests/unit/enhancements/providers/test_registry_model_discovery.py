"""`list_cluster_models_for`: draft discovery narrowed to one picker when it can be.

`kind` is the optional half of the `list_cluster_models` contract, passed only
to a module that declares it — the same rule `credentials_for` applies to
`litellm_credentials` — so a single-endpoint provider keeps its simpler hook.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from enhancements.providers import registry


def _lister_taking_kind(calls: list[dict[str, Any]]):
    async def list_cluster_models(credentials, *, kind=None):
        calls.append({"credentials": credentials, "kind": kind})
        return "listed"

    return SimpleNamespace(__name__="with_kind", list_cluster_models=list_cluster_models)


def _lister_without_kind(calls: list[dict[str, Any]]):
    async def list_cluster_models(credentials):
        calls.append({"credentials": credentials})
        return "listed"

    return SimpleNamespace(__name__="without_kind", list_cluster_models=list_cluster_models)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "embedding"])
async def test_a_lister_that_declares_kind_is_given_it(kind):
    calls: list[dict[str, Any]] = []

    result = await registry.list_cluster_models_for(
        _lister_taking_kind(calls), {"api_key": "t"}, kind=kind
    )

    assert result == "listed"
    assert calls == [{"credentials": {"api_key": "t"}, "kind": kind}]


@pytest.mark.asyncio
async def test_no_kind_is_not_passed_even_to_a_lister_that_declares_it():
    """None means both pickers; the hook's own default says how to list both."""
    calls: list[dict[str, Any]] = []

    await registry.list_cluster_models_for(_lister_taking_kind(calls), {})

    assert calls == [{"credentials": {}, "kind": None}]


@pytest.mark.asyncio
async def test_a_lister_without_kind_is_called_without_it():
    calls: list[dict[str, Any]] = []

    result = await registry.list_cluster_models_for(
        _lister_without_kind(calls), {"api_key": "t"}, kind="embedding"
    )

    assert result == "listed"
    assert calls == [{"credentials": {"api_key": "t"}}]


@pytest.mark.asyncio
async def test_an_unintrospectable_lister_is_called_without_kind(monkeypatch):
    """Assume the base contract rather than risk a TypeError on a real call."""
    calls: list[dict[str, Any]] = []

    def _no_signature(_callable):
        raise ValueError("no signature found")

    monkeypatch.setattr(registry.inspect, "signature", _no_signature)

    await registry.list_cluster_models_for(_lister_without_kind(calls), {}, kind="chat")

    assert calls == [{"credentials": {}}]


def test_the_shipped_listers_follow_the_contract():
    """RHOAI has an endpoint per picker and takes kind; watsonx.ai on-prem has one."""
    from enhancements.providers.redhat import openshift_ai
    from enhancements.providers.watsonx import onprem

    assert registry._hook_accepts_kind(openshift_ai, "list_cluster_models") is True
    assert registry._hook_accepts_kind(onprem, "list_cluster_models") is False
