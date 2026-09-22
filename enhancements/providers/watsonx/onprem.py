"""IBM watsonx.ai running on-premises (Cloud Pak for Data / IBM Software Hub).

The on-prem product speaks the same `/ml/v1/*` REST API as watsonx.ai on IBM
Cloud, so it routes through LiteLLM's `watsonx` provider — no second transport.
What differs is everything around the call:

- **Authentication.** IBM Cloud mints an IAM bearer from an API key; a CPD
  cluster has no IAM. It accepts `Authorization: ZenApiKey <base64(user:apikey)>`
  instead, which is what an operator's cluster username and API key become here.
  LiteLLM already knows that scheme (`zen_api_key`), and it is the *only* one
  that survives both call paths in litellm 1.84: a `token=` kwarg is echoed back
  into the request body, and a hand-set `Authorization` header is ignored on the
  embeddings path, which then calls IBM Cloud IAM and fails on a cluster that
  has no route to it.
- **Credentials are per-deployment.** A cluster URL, not a region endpoint, and
  the SaaS provider's `project_id` is usually a deployment `space_id` instead.
  Most clusters require one: verified against a Cloud Pak for Data 5.x install,
  every `/ml/v1/text/*` call without one is refused with "Missing either
  space_id or project_id or wml_instance_crn", and `GET /v2/spaces` is what
  lists the ids. The watsonx.ai lightweight engine is the exception and has
  neither — see `install_litellm_compatibility` for what supporting that costs.
- **Models are whatever the operator deployed**, so the catalogue ids come from
  `config/model_providers.yaml` rather than LiteLLM's IBM Cloud price table.

- **Models are listed from the cluster**, unfiltered, and split into the two
  pickers here. The API's `filters` grammar is a SaaS convenience and a cluster
  that rejects it would empty both pickers; splitting on each entry's own
  `functions`/`task_ids` cannot fail that way.

The provider key is OpenRAG's own; `LITELLM_PROVIDER` is what it routes as.
Nothing here imports OpenRAG config — `config_manager`, `model_catalog` and
`llm_gateway` all read this module, so it has to stay a leaf.

Verified end to end against a Cloud Pak for Data 5.x cluster: ZenApiKey accepted
on `/ml/v1`, model listing, chat, streaming chat, embeddings and tool calling.

TLS: provider-scoped certificate verification
---------------------------------------------
A CPD cluster is usually fronted by an internal or self-signed CA. TLS trust is
stored with this provider as ``ssl_verify``: ``true`` uses OpenRAG's trust
store, ``false`` disables verification for development, and any other value is
the path to a mounted CA bundle.

LiteLLM's watsonx adapter does not consistently consume an ``ssl_verify`` call
kwarg. It does accept an explicit HTTP client on both chat and embedding paths,
so ``litellm_credentials`` supplies a cached ``AsyncHTTPHandler`` configured
for this provider. That keeps the setting away from OpenAI, Anthropic, and
every other provider in the process. OpenRAG's health check and model discovery
resolve the same stored value for their direct httpx calls.

The CA path is on the backend filesystem, not the browser's. In Kubernetes,
mount the cluster CA into the backend pod. Use a bundle containing both the
public roots and the cluster CA when this deployment also calls public
providers.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, NamedTuple, cast
from urllib.parse import urlsplit, urlunsplit

from utils.logging_config import get_logger

logger = get_logger(__name__)

#: OpenRAG's key for the provider: the name in `model_providers.yaml`, in the
#: settings payload, and in a `watsonx_onprem:<model>` id.
PROVIDER_KEY = "watsonx_onprem"

#: The LiteLLM provider it is routed as. `watsonx_onprem/<model>` is not a
#: prefix LiteLLM can resolve, so the gateway swaps in this key when it builds
#: the model string.
LITELLM_PROVIDER = "watsonx"

#: Credential form for the settings dialog. LiteLLM publishes a `watsonx` form,
#: but it asks for an IBM Cloud API key and a pre-encoded Zen key — neither is
#: what a CPD operator has in hand. These are the fields behind the cluster's
#: own `/icp4d-api/v1/authorize` call: a username and an API key.
CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "api_base",
        "label": "Cluster URL",
        "placeholder": "https://cpd-cluster.example.com",
        "tooltip": "Base URL of the Cloud Pak for Data cluster, with no /ml/v1 suffix.",
        "required": True,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "username",
        "label": "Username",
        "placeholder": None,
        "tooltip": "Your Cloud Pak for Data username. Required alongside the API key: "
        "the two are combined into the ZenApiKey the cluster authenticates with, and an "
        "API key on its own cannot authenticate to a cluster. Not needed if you paste a "
        "Zen API key below instead.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "api_key",
        "label": "API key",
        "placeholder": None,
        "tooltip": "Your Cloud Pak for Data API key (Profile and settings > API key).",
        "required": False,
        "field_type": "password",
        "options": None,
        "default_value": None,
    },
    {
        "key": "zen_api_key",
        "label": "Zen API key",
        "placeholder": None,
        "tooltip": "Optional. A pre-encoded base64(username:apikey). Leave blank to have "
        "OpenRAG build it from the username and API key above.",
        "required": False,
        "field_type": "password",
        "options": None,
        "default_value": None,
    },
    {
        "key": "space_id",
        "label": "Deployment space ID",
        "placeholder": None,
        "tooltip": "The deployment space the models are served from. Most clusters "
        "require this (or a project ID) and reject inference without it. Find it under "
        "Deployments in the console, or with GET /v2/spaces on the cluster. Leave blank "
        "only on a lightweight-engine install, which uses neither spaces nor projects.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "project_id",
        "label": "Project ID",
        "placeholder": None,
        "tooltip": "Optional. Set only if this cluster serves models from a project "
        "rather than a deployment space.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "ssl_verify",
        "label": "TLS certificate verification",
        "placeholder": "/etc/ssl/certs/openrag-ca.pem",
        "tooltip": "Verify the cluster certificate using OpenRAG's trust store, or provide "
        "the backend path to a mounted CA bundle. Disabling verification is for local "
        "development only.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": "true",
    },
]

#: Fields an operator fills in that are not LiteLLM kwargs. `username` is half
#: of the Zen key and nothing else. `ssl_verify` configures the provider's HTTP
#: client rather than the request body. Forwarding either would leak it into the
#: watsonx request payload.
_LOCAL_ONLY_FIELDS = frozenset({"username", "ssl_verify"})

_FALSE_TLS_VALUES = frozenset({"false", "0", "no", "off"})
_TRUE_TLS_VALUES = frozenset({"true", "1", "yes", "on"})
_reported_tls_settings: set[str] = set()


def _values(stored: Mapping[str, Any] | None) -> dict[str, str]:
    """Stored form values as trimmed strings, excluding runtime objects."""
    values: dict[str, str] = {}
    for name, value in (stored or {}).items():
        if name == "client":
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None or isinstance(value, (list, tuple, dict, set)):
            continue
        else:
            text = str(value).strip()
        if text:
            values[str(name)] = text
    return values


def _warn_once(setting: str, message: str, **fields: Any) -> None:
    if setting in _reported_tls_settings:
        return
    _reported_tls_settings.add(setting)
    logger.warning(message, **fields)


def resolve_ssl_verify(value: Any) -> bool | str:
    """Resolve a provider TLS value without consulting process-wide settings."""
    raw = str(value if value is not None else "").strip()
    if not raw or raw.lower() in _TRUE_TLS_VALUES:
        return True
    if raw.lower() in _FALSE_TLS_VALUES:
        _warn_once(
            "disabled",
            "TLS verification is disabled for watsonx.ai on-prem. This is a "
            "development-only setting; never use it on a deployed environment.",
        )
        return False
    if not os.path.isfile(raw):
        raise ValueError(f"The watsonx.ai on-prem CA bundle path does not exist: {raw}")
    return raw


@lru_cache(maxsize=8)
def _http_client_for(ssl_setting: bool | str) -> Any:
    """One reusable LiteLLM async client per provider TLS configuration."""
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    return AsyncHTTPHandler(
        ssl_verify=ssl_setting,
        client_alias="openrag-watsonx-onprem",
    )


def zen_api_key(username: str | None, api_key: str | None) -> str:
    """`base64(username:apikey)` — the value CPD expects after `ZenApiKey `.

    Empty when either half is missing, so a half-filled form does not produce a
    credential that looks valid and 401s on first use.
    """
    user = (username or "").strip()
    key = (api_key or "").strip()
    if not user or not key:
        return ""
    return base64.b64encode(f"{user}:{key}".encode()).decode("ascii")


def litellm_credentials(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Stored form values as LiteLLM kwargs for `watsonx`.

    `api_key` is set to the Zen key as well as `zen_api_key`: the embeddings
    path rejects the call before it ever reads the auth header if `api_key` is
    unset, and the header it then builds comes from `zen_api_key`, so the two
    have to travel together.

    An explicit client carries this provider's TLS policy. Passing
    ``ssl_verify`` itself is ineffective on watsonx and risks it reaching the
    request body through adapters that treat unknown kwargs as payload fields.
    """
    values = _values(stored)
    zen = values.get("zen_api_key") or zen_api_key(values.get("username"), values.get("api_key"))

    credentials: dict[str, Any] = {
        name: value
        for name, value in values.items()
        if name not in _LOCAL_ONLY_FIELDS and name not in {"api_key", "zen_api_key"}
    }
    if zen:
        credentials["zen_api_key"] = zen
        credentials["api_key"] = zen
    elif values.get("api_key"):
        # No username to pair it with. Hand LiteLLM the raw key so a cluster
        # fronted by IBM Cloud IAM still works, rather than dropping the only
        # secret the operator supplied.
        credentials["api_key"] = values["api_key"]
    if credentials:
        credentials["client"] = _http_client_for(resolve_ssl_verify(values.get("ssl_verify")))
        install_litellm_compatibility()
    return credentials


#: Catalogue endpoint used to check credentials. It needs no model, no project
#: and no space, which is what makes it a health check the provider can pass
#: before anything has been selected in Settings.
MODEL_SPECS_PATH = "/ml/v1/foundation_model_specs"

#: Pinned to what LiteLLM itself calls with, so the health check exercises the
#: same API contract as real traffic rather than a newer one the cluster may
#: not serve.
API_VERSION = "2024-03-13"


def auth_header(stored: Mapping[str, Any]) -> str:
    """The `Authorization` value for OpenRAG's own calls to the cluster."""
    values = _values(stored)
    zen = values.get("zen_api_key") or zen_api_key(values.get("username"), values.get("api_key"))
    if zen:
        return f"ZenApiKey {zen}"
    # Deliberately no `Bearer <api_key>` fallback. A Cloud Pak for Data API key
    # is not a bearer token — returning nothing lets the health check report
    # incomplete credentials instead of a misleading rejected-key error.
    return ""


def model_specs_url(api_base: str) -> str:
    """The catalogue URL on `api_base`, however the operator typed the cluster URL.

    Deliberately carries no query string. httpx *replaces* a URL's query when
    it is given `params`, so a `?version=` baked in here is silently dropped by
    any caller that also pages or filters — and the cluster answers
    `invalid_version_date_pattern` for the empty version that results.
    Everything goes through `model_specs_params` instead.
    """
    return f"{(api_base or '').rstrip('/')}{MODEL_SPECS_PATH}"


def model_specs_params(**extra: Any) -> dict[str, Any]:
    """Query parameters for the catalogue endpoint. `version` is mandatory."""
    return {"version": API_VERSION, **extra}


def _error_details(response: Any) -> str:
    """Extract the concise error that Cloud Pak for Data returned."""
    try:
        body = response.json()
    except (ValueError, TypeError):
        return str(getattr(response, "text", ""))[:500]
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or errors[0].get("code") or response.text[:500])
        return str(
            body.get("errorMessage")
            or body.get("message")
            or body.get("detail")
            or response.text[:500]
        )
    return str(getattr(response, "text", ""))[:500]


async def _http_request_with_retry(
    method: str,
    url: str,
    *,
    client: Any,
    max_retries: int = 2,
    backoff_factor: float = 0.5,
    **kwargs: Any,
) -> Any:
    """Retry CPD catalogue reads without depending on API validation helpers."""
    import httpx

    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            if attempt == max_retries:
                raise exc
        await asyncio.sleep(backoff_factor * (2**attempt))
    raise RuntimeError(f"CPD request to {url} failed after retries")


async def lightweight_health_check(credentials: Mapping[str, Any]) -> None:
    """Validate CPD connectivity and Zen credentials without selecting a model."""
    import httpx

    api_base = str(credentials.get("api_base") or "").strip()
    if not api_base:
        raise Exception("No cluster URL is configured for watsonx.ai on-prem")
    header = auth_header(credentials)
    if not header:
        raise Exception(
            "No credentials are configured for watsonx.ai on-prem. "
            "Enter a username and API key, or a Zen API key."
        )

    url = model_specs_url(api_base)
    try:
        async with httpx.AsyncClient(verify=ssl_verify(credentials)) as client:
            response = await _http_request_with_retry(
                "GET",
                url,
                client=client,
                headers={"Authorization": header, "Accept": "application/json"},
                params=model_specs_params(limit=1),
                timeout=10.0,
            )
    except httpx.TimeoutException:
        logger.error("watsonx.ai on-prem health check timed out")
        raise Exception("The watsonx.ai cluster did not respond in time") from None
    except Exception:
        logger.error("watsonx.ai on-prem health check could not reach the cluster", exc_info=True)
        raise

    if response.status_code == 200:
        logger.info("watsonx.ai on-prem health check passed")
        return
    details = _error_details(response)
    logger.error("watsonx.ai on-prem health check failed: %s - %s", response.status_code, details)
    if response.status_code in (401, 403):
        raise Exception(f"Invalid credentials for the watsonx.ai cluster: {details}")
    raise Exception(details)


def ssl_verify(stored: Mapping[str, Any] | None = None) -> bool | str:
    """The provider-scoped TLS setting used by direct and LiteLLM calls."""
    return resolve_ssl_verify(_values(stored).get("ssl_verify"))


#: How long a fetched model list is reused. The set of deployed models changes
#: when an administrator deploys one, not per request.
MODELS_TTL_SECONDS = 300

#: Page size asked for. A cluster serves tens of models, not thousands, but the
#: endpoint pages by default and a truncated list silently hides models.
MODELS_PAGE_LIMIT = 200

#: Guard against following `next` for ever if a cluster paginates oddly.
MAX_MODEL_PAGES = 10

#: `functions` / `task_ids` markers that say which picker a model belongs in.
#: The listing is fetched unfiltered and split here rather than with the API's
#: `filters` parameter: the filter grammar is a SaaS convenience, and a cluster
#: that does not accept it would answer 400 and leave both pickers empty.
_EMBEDDING_FUNCTIONS = frozenset({"embedding", "embeddings"})
_CHAT_FUNCTIONS = frozenset({"text_chat", "text_generation", "chat", "generation"})


class ClusterModels(NamedTuple):
    chat: tuple[str, ...]
    embedding: tuple[str, ...]


_models_cache: dict[str, Any] = {"key": None, "at": 0.0, "value": None}


def cached_models() -> ClusterModels | None:
    """The last model list fetched from the cluster, if it is still fresh."""
    value = _models_cache["value"]
    if value is None or time.monotonic() - _models_cache["at"] > MODELS_TTL_SECONDS:
        return None
    return value


def _cache_key(credentials: Mapping[str, Any]) -> str:
    """Identify the cluster, credentials, and TLS policy behind a model list."""
    values = _values(credentials)
    zen = values.get("zen_api_key") or zen_api_key(values.get("username"), values.get("api_key"))
    tls = values.get("ssl_verify", "true").lower()
    return f"{values.get('api_base', '')}|{zen}|{tls}"


def _resource_markers(resource: Mapping[str, Any]) -> set[str]:
    """Everything a listing entry says about what it can do, lowercased."""
    markers: set[str] = set()
    for function in resource.get("functions") or []:
        if isinstance(function, Mapping) and function.get("id"):
            markers.add(str(function["id"]).lower())
        elif isinstance(function, str):
            markers.add(function.lower())
    for task in resource.get("task_ids") or []:
        markers.add(str(task).lower())
    return markers


def _is_withdrawn(resource: Mapping[str, Any]) -> bool:
    """Whether the cluster still lists a model it has already retired."""
    lifecycle = resource.get("lifecycle")
    if isinstance(lifecycle, list):
        return any(
            isinstance(entry, Mapping) and str(entry.get("id", "")).lower() == "withdrawn"
            for entry in lifecycle
        )
    return str(lifecycle or "").lower() == "withdrawn"


def split_models(resources: Any) -> ClusterModels:
    """Split one `foundation_model_specs` listing into the two picker lists.

    Order is preserved and duplicates dropped. A model that advertises nothing
    useful is treated as a text model: the great majority are, and leaving it
    out would hide something the cluster actually serves.
    """
    chat: list[str] = []
    embedding: list[str] = []
    for resource in resources or []:
        if not isinstance(resource, Mapping):
            continue
        model_id = str(resource.get("model_id") or "").strip()
        if not model_id:
            continue
        # `tech_preview` is not requestable on every deployment, and the SaaS
        # listing drops it for the same reason.
        if resource.get("input_tier") == "tech_preview" or _is_withdrawn(resource):
            continue
        markers = _resource_markers(resource)
        bucket = embedding if markers & _EMBEDDING_FUNCTIONS else chat
        if markers & _EMBEDDING_FUNCTIONS and markers & _CHAT_FUNCTIONS:
            # A model that does both belongs in both pickers.
            if model_id not in chat:
                chat.append(model_id)
        if model_id not in bucket:
            bucket.append(model_id)
    return ClusterModels(chat=tuple(chat), embedding=tuple(embedding))


async def fetch_models(credentials: Mapping[str, Any]) -> ClusterModels | None:
    """Ask the cluster which foundation models it actually serves.

    A cluster serves whatever its operator deployed, so this is the only
    truthful source for the pickers — LiteLLM's bundled table describes IBM
    Cloud, and the `models:` rows in `model_providers.yaml` are the fallback for
    when the cluster cannot be reached.

    The listing is fetched unfiltered and split locally, which keeps this
    working on a lightweight-engine install that has no projects and may not
    accept the SaaS `filters` grammar. Returns None on any failure, so a
    catalogue request never fails because the cluster is unreachable; the caller
    keeps whatever it had.
    """
    import httpx

    values = litellm_credentials(credentials)
    api_base = (values.get("api_base") or "").strip()
    header = auth_header(credentials)
    if not api_base or not header:
        logger.warning(
            "Not listing models on the watsonx.ai cluster: credentials are incomplete. "
            "A cluster URL plus either a username and API key, or a Zen API key, is "
            "needed; the configured model list is used until then.",
            has_cluster_url=bool(api_base),
            has_credentials=bool(header),
        )
        return None

    key = _cache_key(credentials)
    fresh = cached_models()
    if fresh is not None and _models_cache["key"] == key:
        return fresh

    headers = {"Authorization": header, "Accept": "application/json"}
    url = model_specs_url(api_base)
    # Only the first request needs parameters built here; a `next` link already
    # carries its own `version` and `start` in the query it comes back with.
    params: dict[str, Any] | None = model_specs_params(limit=MODELS_PAGE_LIMIT)
    resources: list[Any] = []
    try:
        async with httpx.AsyncClient(verify=ssl_verify(credentials), timeout=15.0) as client:
            for _ in range(MAX_MODEL_PAGES):
                response = await client.get(url, headers=headers, params=params)
                if response.status_code != 200:
                    logger.warning(
                        "watsonx.ai cluster rejected the model listing; "
                        "keeping the configured list",
                        status_code=response.status_code,
                        url=url,
                        body=response.text[:300],
                    )
                    return None
                body = response.json()
                if not isinstance(body, dict):
                    return None
                resources.extend(body.get("resources") or [])
                next_page = body.get("next")
                href = next_page.get("href") if isinstance(next_page, Mapping) else None
                if not href:
                    break
                # Only the path and query are usable. A cluster answers with
                # its own internal hostname here — this one returns
                # `https://wx-inference-proxy-upstream/ml/v1/...`, which does
                # not resolve outside the cluster — so the next page is
                # re-based on the URL the operator gave us.
                parsed = urlsplit(href)
                url = f"{api_base.rstrip('/')}{urlunsplit(('', '', parsed.path, parsed.query, ''))}"
                params = None
    except Exception as exc:
        logger.warning(
            "Could not list models on the watsonx.ai cluster; keeping the configured list",
            error=str(exc),
        )
        return None

    models = split_models(resources)
    if not models.chat and not models.embedding:
        # Far more likely a listing we could not interpret than a cluster with
        # nothing deployed. Emptying both pickers on that guess would be worse
        # than showing the fallback.
        logger.warning(
            "watsonx.ai cluster listed no usable models; keeping the configured list",
            resources=len(resources),
        )
        return None

    _models_cache.update(key=key, at=time.monotonic(), value=models)
    logger.info(
        "Listed models on the watsonx.ai cluster",
        chat=len(models.chat),
        embedding=len(models.embedding),
    )
    return models


def forget_models() -> None:
    """Drop the cached cluster list. For tests and for a credential change."""
    _models_cache.update(key=None, at=0.0, value=None)


# --------------------------------------------------------------------------
# LiteLLM compatibility
# --------------------------------------------------------------------------

#: Modules that bound `_get_api_params` at import time. Patching
#: `common_utils._get_api_params` alone would miss all of them.
_API_PARAM_CALL_SITES = (
    "litellm.llms.watsonx.chat.handler",
    "litellm.llms.watsonx.embed.transformation",
    "litellm.llms.watsonx.completion.transformation",
    "litellm.llms.watsonx.rerank.transformation",
)

_PATCH_MARKER = "_openrag_watsonx_onprem_patched"
_installed = False


def install_litellm_compatibility() -> None:
    """Let a watsonx call proceed with no `project_id` and no `space_id`.

    LiteLLM 1.84 raises 401 locally ("Watsonx project_id and space_id not set")
    before sending anything, and stamps whichever one it has into every request
    body. Both are correct for IBM Cloud. Neither holds for the watsonx.ai
    lightweight engine, whose docs say to omit `project_id` outright — so
    without this the provider cannot reach that install at all.

    The change is deliberately the smallest one that unblocks it: the local
    raise becomes "send it and let the cluster answer", and a `space_id` that
    resolved to null is dropped from the payload instead of being serialised as
    `"space_id": null`. A deployment that *does* have a space or project is
    untouched — both values still flow through exactly as before. The only
    behaviour lost is LiteLLM's client-side check, which on IBM Cloud now
    surfaces as the provider's own error instead of a local one.

    Idempotent, and a no-op on any LiteLLM whose internals have moved.
    """
    global _installed
    if _installed:
        return
    _installed = True  # one attempt per process, success or not

    try:
        import litellm.llms.watsonx.common_utils as common_utils
        from litellm.types.llms.watsonx import WatsonXAPIParams
    except Exception:
        logger.warning(
            "Could not patch LiteLLM for on-prem watsonx.ai; a deployment with no "
            "space_id or project_id will be rejected before the call is sent",
            exc_info=True,
        )
        return

    original_get_api_params = common_utils._get_api_params
    watsonx_error = common_utils.WatsonXAIError

    def _get_api_params_allowing_no_scope(params: dict, model: str | None = None):
        try:
            return original_get_api_params(params=params, model=model)
        except watsonx_error as exc:
            if getattr(exc, "status_code", None) != 401 or "space_id" not in str(exc):
                raise
            # The guard already popped project_id/space_id/region off `params`,
            # and both were absent — which is exactly the lightweight-engine
            # shape. Carry on with an empty scope.
            return WatsonXAPIParams(project_id=None, space_id=None, region_name=None)

    setattr(_get_api_params_allowing_no_scope, _PATCH_MARKER, True)

    patched = []
    for module_name in _API_PARAM_CALL_SITES:
        try:
            module = cast(Any, __import__(module_name, fromlist=["_get_api_params"]))
        except Exception:
            continue
        current = getattr(module, "_get_api_params", None)
        if current is None or getattr(current, _PATCH_MARKER, False):
            continue
        module._get_api_params = _get_api_params_allowing_no_scope
        patched.append(module_name)

    mixin = cast(Any, common_utils.IBMWatsonXMixin)
    if not getattr(mixin._prepare_payload, _PATCH_MARKER, False):
        original_prepare_payload = mixin._prepare_payload

        def _prepare_payload_without_null_scope(self, model: str, api_params) -> dict:
            payload = original_prepare_payload(self, model=model, api_params=api_params)
            if payload.get("space_id") is None:
                # `{"space_id": null}` is not "no space"; watsonx rejects it.
                payload.pop("space_id", None)
            return payload

        setattr(_prepare_payload_without_null_scope, _PATCH_MARKER, True)
        mixin._prepare_payload = _prepare_payload_without_null_scope
        patched.append("IBMWatsonXMixin._prepare_payload")

    if patched:
        logger.info("Enabled scope-less watsonx.ai calls for on-prem", patched=patched)
