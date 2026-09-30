"""Azure AI Foundry, reached over its OpenAI-compatible `/openai/v1` surface.

Foundry exposes the same resource through two inference surfaces:

- ``https://<resource>.services.ai.azure.com/openai/v1`` (and the project form,
  ``.../api/projects/<project>/openai/v1``) — the OpenAI-compatible surface
  Microsoft recommends for new integrations;
- ``https://<resource>.services.ai.azure.com/models`` — the older Foundry
  Models inference route, kept here as a compatibility path for deployments
  already configured against it.

`azure_ai` stays the OpenRAG provider key throughout: it is what a saved model
id (`azure_ai:<deployment>`) carries, what an indexed embedding space is tagged
with (`utils.embedding_fields.get_embedding_space_id`), and what credentials
are stored under. Only the *transport* differs per surface.


Why `hosted_vllm` is the transport for `/openai/v1`
---------------------------------------------------
LiteLLM's own `azure_ai` provider cannot address the v1 surface. Its chat
transformation picks the request path from the **hostname**, not from the path
the operator supplied::

    # litellm/llms/azure_ai/chat/transformation.py
    if "services.ai.azure.com" in api_base:
        new_url = _add_path_to_api_base(api_base, ending_path="/models/chat/completions")
    else:
        new_url = _add_path_to_api_base(api_base, ending_path="/chat/completions")

`_add_path_to_api_base` only collapses *overlapping* segments, and `openai/v1`
does not overlap `models/chat/completions`, so the rewrite lands after the
operator's path. Captured on the wire against a Foundry-shaped hostname:

===========================  =============================================
`api_base`                   path litellm actually requests
===========================  =============================================
``…/openai/v1``              ``/openai/v1/models/chat/completions``  (404)
``…/api/projects/p/openai/v1``  ``/api/projects/p/openai/v1/models/chat/completions``  (404)
``…/models``                 ``/models/chat/completions``            (correct)
===========================  =============================================

There is no flag, kwarg or `api_version` that opts out — the branch is
unconditional. Verified identical in litellm 1.102.0 (the pinned floor) and
1.103.1 (the newest release inside `>=1.96.2,<2.0.0`), so this is not something
a version bump is about to fix.

So the v1 surface needs an OpenAI-compatible transport that appends nothing but
the endpoint path. Of the candidates, only `hosted_vllm` serves the whole
contract — chat, tool calls, streaming **and** embeddings — on both v1 forms:

======================  =====  =====  ======  ==========
LiteLLM key             chat   tools  stream  embeddings
======================  =====  =====  ======  ==========
``hosted_vllm``         yes    yes    yes     yes
``custom_openai``       yes    yes    yes     **no** (unmapped provider)
``openai_like``         **no** — not dispatchable by ``acompletion`` at all
``openai``              **no** — OpenRAG sends a bare model name for this key
                        (`llm_gateway.resolve_call`), which litellm rejects
======================  =====  =====  ======  ==========

`hosted_vllm` is a generic OpenAI-compatible HTTP transport in litellm; nothing
about it is vLLM-specific on this path. It forwards `tools`, `tool_choice`,
`stream` and `response_format` unchanged, and it is already the transport
`enhancements/providers/redhat/openshift_ai.py` routes as, so its behaviour is
exercised elsewhere in this codebase.

**It is a transport, not an identity.** Nothing outside `litellm_route` should
treat Foundry as `hosted_vllm`: the catalogue, credentials, embedding spaces,
health checks and the settings UI all key on `azure_ai`. The reroute guard in
`llm_gateway` compares the route litellm resolved against what `litellm_route`
asked for, precisely so this intentional difference does not read as a fault.

What the transport costs
------------------------
Routing as `hosted_vllm` takes the model id out of litellm's `azure_ai/*` price
table. Measured:

- ``azure_ai/gpt-6-luna`` -> cost and capability metadata resolve;
- ``hosted_vllm/gpt-6-luna`` -> ``This model isn't mapped yet``.

Two things keep this from mattering much today. OpenRAG does not compute cost
at all, and its one metadata consumer — ``llm_gateway._model_info``, which
reads ``supports_none_reasoning_effort`` to decide a tools-plus-reasoning retry
— falls back to the bare model name, so an id that also exists under a public
vendor (``gpt-6-luna``) still resolves. A Foundry-exclusive one (``Phi-4``)
does not, and that retry will not fire for it on the v1 route.

When cost reporting lands, `completion_cost(..., base_model="azure_ai/<model>")`
restores attribution exactly — verified to the cent against the native route.
That is why a deployment's base model is worth capturing then; it is not
collected here because nothing would read it yet.

Not in scope here
-----------------
Microsoft Entra credentials (`azure_ad_token`, service principal) are
`azure`-only for now. The credential form below is shaped so they can be added
without invalidating anything already stored: add the fields, mirror the
`auth_method` pruning `config_manager.set_credentials` does for `azure`, and
make `api_key` conditionally required.

This module is a leaf on purpose. `config_manager`, `model_catalog` and
`llm_gateway` all import it, so it must not import OpenRAG config.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from utils.logging_config import get_logger

logger = get_logger(__name__)

#: OpenRAG's key for the provider: the name in `model_providers.yaml`, in the
#: settings payload, in an `azure_ai:<deployment>` id, and in the
#: `provider:model` embedding-space id persisted with every indexed chunk.
PROVIDER_KEY = "azure_ai"

#: The route used when the endpoint is the legacy `/models` surface, and the
#: fallback whenever `litellm_route` cannot classify what is stored. LiteLLM's
#: own `azure_ai` handler is correct there and keeps its Foundry price table.
LITELLM_PROVIDER = "azure_ai"

#: The transport for the OpenAI-compatible surface. See the module docstring.
OPENAI_COMPATIBLE_ROUTE = "hosted_vllm"

#: The two kinds of call the gateway makes. Foundry serves both from one
#: endpoint, so `kind` changes nothing here; it is accepted to match the
#: enhancement contract.
CallKind = Literal["chat", "embedding"]

#: Endpoint shapes this module recognises. `unknown` is anything else, which is
#: routed on the safe default rather than guessed at.
Profile = Literal["resource_openai_v1", "project_openai_v1", "legacy_models", "unknown"]

#: Path suffix of the OpenAI-compatible surface, resource and project forms.
_V1_SUFFIX = "/openai/v1"
#: Path suffix of the older Foundry Models inference route.
_LEGACY_SUFFIX = "/models"
#: Marks the project form, which hangs off `/api/projects/<project>`.
_PROJECT_MARKER = "/api/projects/"

#: Endpoint paths an operator pastes from a curl example or the portal's
#: "Target URI" box. They name one call, not the base, and LiteLLM appends its
#: own — so `.../chat/completions` becomes `.../chat/completions/chat/completions`.
_CALL_SUFFIXES = ("/chat/completions", "/embeddings", "/responses")

#: Fields the operator fills in that are not LiteLLM kwargs. Forwarding one
#: would land it in the request body, since LiteLLM passes kwargs it does not
#: recognise straight through.
_LOCAL_ONLY_FIELDS = frozenset({"deployment_names"})


CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "api_base",
        "label": "Endpoint",
        "placeholder": "https://<resource>.services.ai.azure.com/openai/v1",
        "tooltip": (
            "The resource endpoint, not a per-deployment Target URI. Copy the "
            "'Azure AI Foundry' endpoint from your resource's Overview page and keep "
            "the /openai/v1 suffix. A Target URI that names one deployment "
            "(.../openai/deployments/<name>/chat/completions) pins every model you "
            "select to that one deployment. The older /models endpoint is still "
            "accepted for deployments already using it."
        ),
        "required": True,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "api_key",
        "label": "API key",
        "placeholder": None,
        "tooltip": "A key from the resource's Keys and Endpoint page.",
        "required": True,
        "field_type": "password",
        "options": None,
        "default_value": None,
    },
    {
        "key": "api_version",
        "label": "API version",
        "placeholder": "2024-05-01-preview",
        "tooltip": (
            "Only for the older /models endpoint, which dates its API. Leave blank "
            "for /openai/v1, which is versionless — sending one there is at best "
            "ignored."
        ),
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "deployment_names",
        "label": "Deployment names",
        "placeholder": "prod-chat-gpt4o\nprod-embed-3-large",
        "tooltip": (
            "One deployment name per line. Foundry names are chosen by whoever "
            "created the deployment, so the model catalogue cannot know yours. "
            "Listing them here is what puts them in the model pickers."
        ),
        "required": False,
        # `textarea` is the right control for a list, and it also lands this
        # field in `model_catalog.secret_field_keys` — which keys off the field
        # type, not the field's meaning — so deployment names are encrypted at
        # rest alongside the key. Harmless, and not worth a single-line `text`
        # control to avoid; noted because reading config.yaml will show
        # ciphertext where plain names might be expected.
        "field_type": "textarea",
        "options": None,
        "default_value": None,
    },
]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalized_api_base(value: Any) -> str:
    """The endpoint as LiteLLM needs it: no trailing slash, no call path, no query.

    Operators paste three things that all have to work. The portal's endpoint
    box gives the base. A curl example gives the base plus `/chat/completions`.
    LiteLLM's own (misleading) placeholder gives a per-deployment Target URI
    with `?api-version=` attached.

    Nothing is ever *appended* here. Guessing a suffix is how `/openai/v1` and
    `/models` get confused for one another, and the two are different APIs.
    """
    raw = _clean(value)
    if not raw:
        return ""

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")

    path = parts.path.rstrip("/")
    for suffix in _CALL_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break

    # The query is always dropped: `api-version` belongs in its own field, and
    # a v1 endpoint has no use for it at all.
    normalized = urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))
    if normalized != raw:
        logger.debug(
            "Normalized the Azure AI Foundry endpoint",
            original=raw,
            normalized=normalized,
        )
    return normalized


def endpoint_profile(api_base: Any) -> Profile:
    """Which Foundry surface `api_base` names.

    Classified on the path alone. The hostname deliberately does not take part:
    a Foundry resource can serve Azure OpenAI deployments too, so the host says
    nothing about which API is being addressed — which is the same reason
    `provider_validation.is_azure_ai_foundry_endpoint` exists separately.
    """
    base = normalized_api_base(api_base)
    if not base:
        return "unknown"
    path = urlsplit(base).path.rstrip("/").lower()
    if path.endswith(_V1_SUFFIX):
        return "project_openai_v1" if _PROJECT_MARKER in path else "resource_openai_v1"
    if path.endswith(_LEGACY_SUFFIX) or not path:
        # A bare resource root is the legacy route's own default: LiteLLM's
        # `azure_ai` handler appends `/models/...` to it and reaches the right
        # place.
        return "legacy_models"
    return "unknown"


def litellm_route(stored: Mapping[str, Any] | None) -> str:
    """The LiteLLM transport for the endpoint in `stored`.

    The one place that maps a Foundry surface onto a transport. Everything else
    — the catalogue, the settings form, credentials, embedding spaces — keeps
    calling this provider `azure_ai`.

    An unrecognised endpoint falls back to `azure_ai` rather than guessing at
    the OpenAI-compatible transport: the legacy handler produces a *wrong* URL
    for the v1 surface, but the OpenAI-compatible one produces a *plausible*
    URL for anything, which fails later and less legibly.
    """
    profile = endpoint_profile((stored or {}).get("api_base"))
    if profile in ("resource_openai_v1", "project_openai_v1"):
        return OPENAI_COMPATIBLE_ROUTE
    return LITELLM_PROVIDER


def _require_https(api_base: str) -> None:
    """Refuse an `http://` Foundry endpoint outright.

    `openshift_ai` only warns about this, because a cluster-local predictor or
    an `oc port-forward` is legitimately plain HTTP. Foundry has no such case:
    it is a public cloud service, and a cleartext endpoint means the API key
    crosses the internet in the clear. `docling_service` already rejects
    non-HTTPS for both Azure providers, so this matches the stricter of the two
    precedents in this repository.

    A value with *no* scheme is not judged here. It is not a URL at all, and
    `endpoint_profile` reports that in terms the operator can act on — telling
    someone who typed a hostname that it "must use https://" sends them to fix
    the wrong half of it.
    """
    if not api_base:
        return
    scheme = urlsplit(api_base).scheme.lower()
    if scheme and scheme != "https":
        raise ValueError(
            "The Azure AI Foundry endpoint must use https://. A plain-HTTP endpoint "
            "would send the API key in cleartext."
        )


def deployment_names(stored: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Deployment names the operator listed, in order, de-duplicated.

    Accepts newline, comma or whitespace separation, because the field is a
    textarea and people paste all three.
    """
    raw = _clean((stored or {}).get("deployment_names")).replace(",", "\n")
    seen: dict[str, None] = {}
    for line in raw.split("\n"):
        name = line.strip()
        if name:
            seen.setdefault(name, None)
    return tuple(seen)


def litellm_credentials(stored: Mapping[str, Any], *, kind: CallKind = "chat") -> dict[str, Any]:
    """LiteLLM kwargs for a Foundry call.

    `kind` is accepted for the enhancement contract and ignored: Foundry serves
    chat and embeddings from one endpoint.
    """
    del kind  # one endpoint serves both

    api_base = normalized_api_base(stored.get("api_base"))
    _require_https(api_base)

    credentials: dict[str, Any] = {
        name: value
        for name, value in stored.items()
        if name not in _LOCAL_ONLY_FIELDS and name not in {"api_base", "api_version"}
    }
    if api_base:
        credentials["api_base"] = api_base

    # `api-version` is a legacy-route concept. On `/openai/v1` it is at best
    # ignored, and LiteLLM would append it as a query parameter, so it is
    # dropped rather than forwarded onto a versionless API.
    api_version = _clean(stored.get("api_version"))
    if api_version and endpoint_profile(api_base) == "legacy_models":
        credentials["api_version"] = api_version

    return credentials


#: Read-only listing used to check credentials. It needs no deployment and
#: bills nothing, which is what makes it a check the provider can pass before
#: anything has been selected in Settings. Both surfaces expose it directly
#: under the endpoint.
MODELS_PATH = "/models"

#: A human is waiting on the pre-save check, so it fails fast.
HEALTH_TIMEOUT_SECONDS = 15.0


def models_url(api_base: str) -> str:
    """The deployment/model listing URL for an endpoint.

    On the v1 surface this is `…/openai/v1/models`. On the legacy route the
    endpoint *is* `…/models`, and the listing hangs off the resource root
    instead, so the suffix is not doubled.
    """
    base = normalized_api_base(api_base)
    if endpoint_profile(base) == "legacy_models":
        return (
            base if base.rstrip("/").endswith(MODELS_PATH) else f"{base.rstrip('/')}{MODELS_PATH}"
        )
    return f"{base.rstrip('/')}{MODELS_PATH}"


def health_headers(stored: Mapping[str, Any]) -> dict[str, str]:
    """Auth headers for OpenRAG's own read-only calls to Foundry.

    Both header styles are sent. Microsoft's v1 surface takes
    `Authorization: Bearer`, the legacy `/models` route documents `api-key`,
    and litellm itself is inconsistent across the two — its `azure_ai` chat
    path sends `api-key` while its embedding path sends `Bearer` to the same
    endpoint. Sending both costs nothing and keeps the probe from failing for
    a reason that has nothing to do with whether the credential is valid.
    """
    api_key = _clean(stored.get("api_key"))
    if not api_key:
        return {}
    return {"api-key": api_key, "Authorization": f"Bearer {api_key}"}


async def lightweight_health_check(credentials: Mapping[str, Any]) -> None:
    """Validate the endpoint and key without selecting or billing a deployment.

    Raises `ValueError` for a form that cannot be called at all, and a plain
    `Exception` carrying the upstream detail for a call that was rejected.

    A 403 is *not* treated as a bad credential: listing deployments can need a
    permission an inference-only identity lacks, and reporting "invalid key"
    for it would send the operator after the wrong problem. See the message
    below.
    """
    import httpx

    api_base = normalized_api_base(credentials.get("api_base"))
    if not api_base:
        raise ValueError("The Azure AI Foundry endpoint is required")
    _require_https(api_base)
    if endpoint_profile(api_base) == "unknown":
        raise ValueError(
            "The Azure AI Foundry endpoint should end in /openai/v1 (recommended) "
            "or /models. Copy it from the resource's Overview page rather than "
            "from a single deployment's Target URI."
        )
    headers = health_headers(credentials)
    if not headers:
        raise ValueError("An Azure AI Foundry API key is required")

    async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
        response = await client.get(models_url(api_base), headers=headers)

    if response.status_code == 403:
        raise PermissionError(
            "The credentials were accepted but this identity cannot list deployments. "
            "Inference may still work; enter a deployment name to use it."
        )
    if response.status_code >= 400:
        detail = response.text[:400] if response.text else f"HTTP {response.status_code}"
        raise Exception(detail)
