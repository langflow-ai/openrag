"""Registry for provider-specific enhancements.

Most providers use the declarative LiteLLM path.  Entries here are reserved for
deployment shapes that need their own credentials, route alias, model discovery,
or validation protocol.
"""

from __future__ import annotations

from types import ModuleType

from enhancements.providers.watsonx import onprem

_ENHANCEMENTS: dict[str, ModuleType] = {
    onprem.PROVIDER_KEY: onprem,
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
