"""Registry for provider-specific enhancements.

Most providers use the declarative LiteLLM path.  Entries here are reserved for
deployment shapes that need their own credentials, route alias, model discovery,
or validation protocol.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Mapping
from types import ModuleType
from typing import Any

from enhancements.providers.azure import foundry
from enhancements.providers.redhat import openshift_ai
from enhancements.providers.watsonx import onprem

_ENHANCEMENTS: dict[str, ModuleType] = {
    onprem.PROVIDER_KEY: onprem,
    openshift_ai.PROVIDER_KEY: openshift_ai,
    foundry.PROVIDER_KEY: foundry,
}


def get(provider: str) -> ModuleType | None:
    """Return the enhancement registered for an OpenRAG provider key."""
    return _ENHANCEMENTS.get((provider or "").strip().lower())


def route_aliases() -> dict[str, str]:
    """OpenRAG provider keys that LiteLLM must route under another key.

    The *static* half of routing: one alias per provider, fixed at import. A
    provider whose route depends on how it was configured declares
    `litellm_route` as well — see `litellm_route_for`. This mapping is still
    what that provider falls back to, so it must stay the safe default.
    """
    return {
        key: enhancement.LITELLM_PROVIDER
        for key, enhancement in _ENHANCEMENTS.items()
        if hasattr(enhancement, "LITELLM_PROVIDER")
    }


def litellm_route_for(provider: str, stored: Mapping[str, Any] | None) -> str | None:
    """The LiteLLM key `provider` routes as *for this configuration*.

    Most providers reach one API one way, and `LITELLM_PROVIDER` says which.
    Azure AI Foundry does not: the endpoint an operator pastes decides which
    LiteLLM transport can even produce a correct URL for it, so the route has
    to be recomputed per configuration rather than fixed at import.

    Returns `None` when `provider` has no enhancement or the enhancement has
    nothing to say, leaving the caller on the static alias.
    """
    enhancement = get(provider)
    if enhancement is None:
        return None
    resolve = getattr(enhancement, "litellm_route", None)
    if resolve is None:
        return getattr(enhancement, "LITELLM_PROVIDER", None)
    # Deliberately not guarded. A hook that raises is reporting a configuration
    # it cannot route, and quietly substituting the static alias would turn
    # that into a wrong request rather than a clear error — the caller decides
    # how to surface it.
    return resolve(stored or {}) or None


def credential_field_overrides() -> dict[str, list[dict[str, object]]]:
    """Settings forms supplied by provider enhancements instead of LiteLLM."""
    return {
        key: enhancement.CREDENTIAL_FIELDS
        for key, enhancement in _ENHANCEMENTS.items()
        if hasattr(enhancement, "CREDENTIAL_FIELDS")
    }


def enhancements() -> tuple[ModuleType, ...]:
    """All registered enhancements, for generic catalogue refreshes."""
    return tuple(_ENHANCEMENTS.values())


def credentials_for(
    enhancement: ModuleType,
    stored: Mapping[str, Any],
    kind: str = "chat",
) -> dict[str, Any]:
    """Translate stored form values into LiteLLM kwargs for one kind of call.

    `kind` is the *optional* half of the enhancement contract. Most providers
    reach one API with one set of credentials and take the stored values alone;
    Red Hat OpenShift AI serves chat and embeddings from two separate
    `InferenceService`s, so it has to know which endpoint the caller wants.

    `kind` is passed only to a module whose `litellm_credentials` declares it,
    so every other enhancement — and any future one written against the simpler
    signature — keeps working unchanged. The flip side is that a module which
    *needs* `kind` but drops it from its signature is called without it and
    silently answers for chat; that is a contract error the module's own tests
    have to catch, not something this function can detect.
    """
    translate = enhancement.litellm_credentials
    if _accepts_kind(enhancement):
        return dict(translate(stored, kind=kind))
    return dict(translate(stored))


def runtime_kwargs_for(
    enhancement: ModuleType,
    stored: Mapping[str, Any],
) -> dict[str, Any]:
    """Build optional non-serializable kwargs only at a LiteLLM call boundary."""
    build = getattr(enhancement, "litellm_runtime_kwargs", None)
    return dict(build(stored)) if callable(build) else {}


@functools.cache
def _accepts_kind(enhancement: ModuleType) -> bool:
    """Whether the module's `litellm_credentials` takes a `kind` keyword.

    Cached per module: the answer is fixed for the life of the process, and
    this sits on the path of every gateway request.
    """
    try:
        return "kind" in inspect.signature(enhancement.litellm_credentials).parameters
    except (TypeError, ValueError):
        # A C-implemented or otherwise unintrospectable callable. Assume the
        # base contract rather than risk a TypeError on a real call.
        _log_signature_fallback(getattr(enhancement, "__name__", str(enhancement)))
        return False


def _log_signature_fallback(module_name: str) -> None:
    from utils.logging_config import get_logger

    get_logger(__name__).debug(
        "Could not inspect a provider enhancement's credential translation; "
        "calling it without a call kind",
        module=module_name,
    )
