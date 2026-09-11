"""Registry for provider-specific enhancements.

Most providers use the declarative LiteLLM path.  Entries here are reserved for
deployment shapes that need their own credentials, route alias, model discovery,
or validation protocol.
"""

from __future__ import annotations

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

    Passing `kind` only to a module that declares it keeps every other
    enhancement — and any future one written against the simpler signature —
    working unchanged, and it fails loudly (rather than silently ignoring the
    argument) if a module's signature is ever narrowed by mistake.
    """
    translate = enhancement.litellm_credentials
    try:
        accepts_kind = "kind" in inspect.signature(translate).parameters
    except (TypeError, ValueError):
        # A C-implemented or otherwise unintrospectable callable. Assume the
        # base contract rather than risk a TypeError on a real call.
        logger_warning = getattr(enhancement, "__name__", str(enhancement))
        _log_signature_fallback(logger_warning)
        accepts_kind = False
    if accepts_kind:
        return dict(translate(stored, kind=kind))
    return dict(translate(stored))


def _log_signature_fallback(module_name: str) -> None:
    from utils.logging_config import get_logger

    get_logger(__name__).debug(
        "Could not inspect a provider enhancement's credential translation; "
        "calling it without a call kind",
        module=module_name,
    )
