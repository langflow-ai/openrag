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

from enhancements.providers.redhat import openshift_ai
from enhancements.providers.watsonx import onprem

_ENHANCEMENTS: dict[str, ModuleType] = {
    onprem.PROVIDER_KEY: onprem,
    openshift_ai.PROVIDER_KEY: openshift_ai,
}


def get(provider: str) -> ModuleType | None:
    """Return the enhancement registered for an OpenRAG provider key."""
    return _ENHANCEMENTS.get((provider or "").strip().lower())


def route_aliases() -> dict[str, str]:
    """OpenRAG provider keys that LiteLLM must route under another key."""
    return {
        key: enhancement.LITELLM_PROVIDER
        for key, enhancement in _ENHANCEMENTS.items()
        if hasattr(enhancement, "LITELLM_PROVIDER")
    }


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
