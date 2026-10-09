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
from typing import Any, Literal

from enhancements.providers.aws import bedrock
from enhancements.providers.azure import foundry
from enhancements.providers.redhat import openshift_ai
from enhancements.providers.watsonx import onprem

CallKind = Literal["chat", "embedding"]

_ENHANCEMENTS: dict[str, ModuleType] = {
    onprem.PROVIDER_KEY: onprem,
    openshift_ai.PROVIDER_KEY: openshift_ai,
    bedrock.PROVIDER_KEY: bedrock,
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


def model_discovery_for(provider: str) -> ModuleType | None:
    """The enhancement that can list `provider`'s models from unsaved credentials.

    The optional `list_cluster_models(credentials)` member of the contract: the
    same listing `fetch_models()` caches, without the cache, for a form that is
    asking what a cluster serves before anything is saved. None when the
    provider has no enhancement or the enhancement cannot list its own models.
    """
    enhancement = get(provider)
    if enhancement is None or not callable(getattr(enhancement, "list_cluster_models", None)):
        return None
    return enhancement


async def list_cluster_models_for(
    enhancement: ModuleType,
    credentials: Mapping[str, Any],
    *,
    kind: CallKind | None = None,
) -> Any:
    """Call the module's `list_cluster_models`, narrowed to one picker if it can be.

    `kind` follows the same rule as in `credentials_for`: it is passed only to a
    module whose hook declares it. Red Hat OpenShift AI lists chat and embedding
    models from two endpoints and uses it to ask only the one a picker needs; a
    single-endpoint provider (watsonx.ai on-prem) lists everything at once and
    is called without it. None asks for both pickers.
    """
    if kind is not None and _hook_accepts_kind(enhancement, "list_cluster_models"):
        return await enhancement.list_cluster_models(credentials, kind=kind)
    return await enhancement.list_cluster_models(credentials)


def live_models_for(provider: str, kind: CallKind) -> tuple[str, ...] | None:
    """What `provider` last said it serves for `kind`, if it can say at all.

    None means *unknown*, never "serves nothing": the provider has no
    enhancement, the enhancement cannot list its own models, or nothing fresh
    is cached for that endpoint. Callers must treat None as no information —
    telling an operator their model is missing on the strength of a listing
    that never arrived would be worse than staying quiet.

    An empty tuple is the opposite: a real answer. The provider was listed and
    that endpoint serves nothing of this kind — watsonx on-prem caches exactly
    that for a cluster with chat models and no embedding model — so it must
    reach the caller as `()`, not be folded into unknown. An enhancement that
    cannot tell "empty" from "unreadable" keeps that half None itself.

    The lists come from the enhancement's own TTL cache, so this is a dict
    lookup; refreshing them is `model_catalog.refresh_live_models()`.
    """
    enhancement = get(provider)
    if enhancement is None or not hasattr(enhancement, "cached_models"):
        return None
    try:
        models = enhancement.cached_models()
    except Exception as exc:  # a diagnostic must never take down its caller
        _log_hook_failure(provider, "cached_models", exc)
        return None
    if models is None:
        return None
    listed = getattr(models, kind, None)
    if listed is None:
        return None
    # A bare string would split into characters, and a scalar cannot be
    # iterated at all; either is a malformed cache, so unknown rather than a
    # list of nonsense model ids.
    if isinstance(listed, str | bytes):
        _log_unreadable_listing(provider, kind, listed)
        return None
    try:
        return tuple(str(model) for model in listed)
    except TypeError:
        _log_unreadable_listing(provider, kind, listed)
        return None


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


def embedding_concurrency_for(
    provider: str,
    stored: Mapping[str, Any] | None,
) -> int | None:
    """How many embedding calls the gateway may have in flight to `provider`.

    The optional `embedding_max_concurrency(stored)` member of the enhancement
    contract. None means unlimited: the provider has no enhancement, the
    enhancement sets no limit, or the hook failed. A broken hook must not fail
    the request it would only have throttled, so errors are logged and ignored.
    """
    enhancement = get(provider)
    hook = getattr(enhancement, "embedding_max_concurrency", None)
    if not callable(hook):
        return None
    try:
        limit = hook(stored or {})
    except Exception as exc:
        _log_hook_failure(provider, "embedding_max_concurrency", exc)
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return None
    return limit


def default_auth_method_for(provider: str, stored: Mapping[str, Any] | None) -> str | None:
    """The authentication method to assume for `provider` when none was chosen.

    The optional `default_auth_method(stored)` member of the enhancement
    contract, for a provider whose form offers several methods. None when the
    provider has no such hook, the hook fails (logged and ignored), or it
    returns anything but a non-empty string.
    """
    hook = getattr(get(provider), "default_auth_method", None)
    if not callable(hook):
        return None
    try:
        method = hook(stored or {})
    except Exception as exc:
        _log_hook_failure(provider, "default_auth_method", exc)
        return None
    return method if isinstance(method, str) and method else None


def _log_hook_failure(provider: str, hook: str, exc: Exception) -> None:
    from utils.logging_config import get_logger

    get_logger(__name__).warning(
        "A provider enhancement hook failed; continuing without it",
        provider=provider,
        hook=hook,
        error_type=type(exc).__name__,
        error=str(exc),
    )


def _log_unreadable_listing(provider: str, kind: str, listed: object) -> None:
    from utils.logging_config import get_logger

    get_logger(__name__).warning(
        "A provider enhancement cached a model listing that is not a list; treating it as unknown",
        provider=provider,
        kind=kind,
        listing_type=type(listed).__name__,
    )


@functools.cache
def _accepts_kind(enhancement: ModuleType) -> bool:
    """Whether the module's `litellm_credentials` takes a `kind` keyword.

    Cached per module: the answer is fixed for the life of the process, and
    this sits on the path of every gateway request.
    """
    return _hook_accepts_kind(enhancement, "litellm_credentials")


def _hook_accepts_kind(enhancement: ModuleType, hook: str) -> bool:
    """Whether the module's `hook` takes a `kind` keyword."""
    try:
        return "kind" in inspect.signature(getattr(enhancement, hook)).parameters
    except (TypeError, ValueError):
        # A C-implemented or otherwise unintrospectable callable. Assume the
        # base contract rather than risk a TypeError on a real call.
        _log_signature_fallback(getattr(enhancement, "__name__", str(enhancement)), hook)
        return False


def _log_signature_fallback(module_name: str, hook: str) -> None:
    from utils.logging_config import get_logger

    get_logger(__name__).debug(
        "Could not inspect a provider enhancement hook; calling it without a call kind",
        module=module_name,
        hook=hook,
    )
