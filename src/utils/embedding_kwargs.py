"""Helpers for building extra keyword arguments for embedding-provider calls.

``clients.patched_embedding_client.embeddings.create(...)`` is an
OpenAI-SDK-shaped call. For providers routed through ``agentd``'s
``patch_openai_with_mcp`` (see ``config.settings.patched_async_client``), any
kwargs beyond ``model``/``input`` pass straight through to
``litellm.aembedding(**kwargs)`` when the resolved provider isn't
``openai``. The helpers here build those pass-through kwargs for
Cohere-family embedding models (``input_type``) and, specifically, for
models routed through OCI Generative AI (the ``oci_*`` credential kwargs
litellm's OCI integration requires).
"""

from __future__ import annotations

from typing import Any

COHERE_QUERY_INPUT_TYPE = "search_query"
COHERE_DOCUMENT_INPUT_TYPE = "search_document"

# LiteLLM prefix used to route to OCI Generative AI (see
# services.models_service.KNOWN_PREFIXES).
OCI_LITELLM_PREFIX = "oci/"


def is_cohere_embedding_model(model_name: str) -> bool:
    """Return True if ``model_name`` looks like a Cohere-family embedding model.

    Checks the model name itself rather than the resolved LiteLLM provider
    prefix. Cohere embedding models are served through more than one
    provider prefix (``oci/...`` today, potentially a direct ``cohere/...``
    or ``bedrock/...`` prefix in the future) and all of them expect the same
    ``input_type`` parameter, so keying off the model name is the one check
    that stays correct regardless of which provider ends up routing the
    request.
    """
    return bool(model_name) and "cohere" in model_name.lower()


def cohere_input_type_kwargs(model_name: str, input_type: str) -> dict[str, str]:
    """Return the extra kwargs needed for a Cohere-family embedding call.

    Empty dict for non-Cohere models so callers can unconditionally splat
    the result into ``.embeddings.create(**kwargs)`` without branching.
    """
    if is_cohere_embedding_model(model_name):
        return {"input_type": input_type}
    return {}


def is_oci_litellm_model(formatted_model: str) -> bool:
    """Return True if ``formatted_model`` is routed to OCI Generative AI."""
    return bool(formatted_model) and formatted_model.startswith(OCI_LITELLM_PREFIX)


def oci_credential_kwargs(oci_config: Any, signer: Any | None = None) -> dict[str, Any]:
    """Build the ``oci_*`` kwargs litellm's OCI integration needs per-call.

    ``compartment_id`` and ``region`` are always included regardless of
    auth method -- they scope which resource the request targets, not how
    it's signed. When ``signer`` is provided (built by
    ``utils.oci_auth.build_oci_signer`` for instance_principal/
    workload_identity), it's passed through as ``oci_signer`` and the
    manual user/fingerprint/tenancy/key fields are omitted entirely --
    litellm's ``sign_oci_request`` dispatch uses ``oci_signer`` when
    present and never falls back to manual credentials in that case, so
    including stale/irrelevant key-based fields alongside a signer would
    be misleading, not merely redundant.

    When ``signer`` is None (the "api_key" auth method), behavior is
    unchanged from before this function gained the ``signer`` parameter:
    the manual user/fingerprint/tenancy/key/key_file fields are included
    exactly as litellm's OCI integration requires (see
    litellm/llms/oci/embed/transformation.py and
    litellm/llms/oci/chat/transformation.py, verified directly against the
    installed litellm==1.84.0 source: OCI credentials are read exclusively
    from call-time kwargs, never from the environment, so these must be
    passed explicitly on every call).

    Args:
        oci_config: The ``OCIConfig`` from ``OpenRAGConfig.providers.oci``.
        signer: A pre-built OCI SDK Signer object, or None for api_key auth.

    Returns:
        A dict of only the fields that are actually set, so callers can
        unconditionally splat the result into ``.embeddings.create(**kwargs)``.
    """
    kwargs: dict[str, Any] = {}
    if getattr(oci_config, "compartment_id", None):
        kwargs["oci_compartment_id"] = oci_config.compartment_id
    if getattr(oci_config, "region", None):
        kwargs["oci_region"] = oci_config.region

    if signer is not None:
        kwargs["oci_signer"] = signer
        return kwargs

    if getattr(oci_config, "user", None):
        kwargs["oci_user"] = oci_config.user
    if getattr(oci_config, "fingerprint", None):
        kwargs["oci_fingerprint"] = oci_config.fingerprint
    if getattr(oci_config, "tenancy", None):
        kwargs["oci_tenancy"] = oci_config.tenancy
    if getattr(oci_config, "key", None):
        kwargs["oci_key"] = oci_config.key
    if getattr(oci_config, "key_file", None):
        kwargs["oci_key_file"] = oci_config.key_file
    return kwargs
