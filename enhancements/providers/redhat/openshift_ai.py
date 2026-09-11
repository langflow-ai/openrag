"""Red Hat OpenShift AI (RHOAI) — models served in the customer's own cluster.

RHOAI serves models through `KServe` + `vLLM`, and `vLLM` speaks the OpenAI HTTP
API. So there is no new transport here: the provider routes through LiteLLM's
`hosted_vllm` key, the same one any self-hosted vLLM endpoint uses. What differs
is everything around the call:

- **One endpoint per model.** `vLLM` serves a single model per deployment, so a
  RAG stack needs *two* `InferenceService`s — one for chat, one for embeddings —
  at two different URLs. That is the whole reason this module exists rather than
  a plain `hosted_vllm` row in `model_providers.yaml`: LiteLLM takes one
  `api_base` per call, so something has to choose which one, and only the caller
  knows whether it is embedding or completing. `litellm_credentials` therefore
  takes a `kind`, which is the optional half of the enhancement contract (see
  `credentials_for` in `enhancements/providers/registry.py`).
- **Authentication is a Kubernetes bearer token.** An `InferenceService`
  annotated `security.opendatahub.io/enable-auth: "true"` is fronted by a
  `kube-rbac-proxy` that runs a `TokenReview` and then a `SubjectAccessReview`:
  the token's subject needs `get` on `inferenceservices` in the model namespace.
  A `ServiceAccount` token is what an operator has in hand, and it goes out as
  an ordinary `Authorization: Bearer`, which is exactly what `api_key` becomes.
- **Models are whatever the operator deployed**, so the catalogue ids come from
  each endpoint's own `GET /v1/models` rather than LiteLLM's price table, which
  knows no `hosted_vllm` models at all.

The provider key is OpenRAG's own; `LITELLM_PROVIDER` is what it routes as.
Nothing here imports OpenRAG config — `config_manager`, `model_catalog` and
`llm_gateway` all read this module, so it has to stay a leaf.

Verified end to end against an `RHOAI` 3.5.0 cluster (`vLLM 0.24.0+rhaiv.9`,
CPU x86 runtime): model listing, chat and embeddings on both endpoints, with the
`ServiceAccount` token and the projected service CA.

Why `hosted_vllm` and not `openai_like`
---------------------------------------
Both are OpenAI-compatible passthrough keys, and either would carry the traffic.
`hosted_vllm` is the one that carries the **TLS setting** with it. Verified
against litellm 1.84 and a live cluster, both chat and embeddings:

- `hosted_vllm` dispatches through `base_llm_http_handler`, which reads
  `litellm_params["ssl_verify"]` — a per-call `ssl_verify=` is honoured.
- `openai_like` dispatches through `OpenAILikeChatHandler` /
  `OpenAILikeEmbeddingHandler`, neither of which mentions `ssl_verify`. The
  kwarg is silently dropped and the call fails with
  `ssl:True [SSLCertVerificationError: ... self-signed certificate in
  certificate chain]` against a cluster CA — or, worse, would quietly verify
  against the system store when the operator believed they had configured trust.

That difference is the whole reason TLS trust can be a per-provider field here
rather than the process-wide `SSL_CERT_FILE` that watsonx.ai on-prem is stuck
with (see `enhancements/providers/watsonx/onprem.py`). Do not "simplify" this to
`openai_like`.

TLS: trusting the cluster's service-serving CA
----------------------------------------------
An in-cluster `Service` presents a certificate signed by OpenShift's
service-serving CA, which is not in any container's default trust store.
OpenShift projects that CA into every pod, so the fix is a path, not a mount::

    RHOAI_TLS_VERIFY=/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt

`ssl_verify` rides in the credential bag and is scoped to this provider only —
unlike `SSL_CERT_FILE`, which *replaces* certifi's roots process-wide and would
break every public provider in the same deployment.

`RHOAI_TLS_VERIFY=false` disables verification and exists for one case: an
`oc port-forward` to `localhost`, where the certificate cannot match. It is
development-only and must never be set on a deployed environment.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, Literal, NamedTuple
from urllib.parse import urlsplit, urlunsplit

from utils.logging_config import get_logger

logger = get_logger(__name__)

#: OpenRAG's key for the provider: the name in `model_providers.yaml`, in the
#: settings payload, and in a `rhoai:<model>` id.
PROVIDER_KEY = "rhoai"

#: The LiteLLM provider it is routed as. `rhoai/<model>` is not a prefix LiteLLM
#: can resolve, so the gateway swaps in this key when it builds the model
#: string. See the module docstring for why this is `hosted_vllm`.
LITELLM_PROVIDER = "hosted_vllm"

#: The two kinds of call the gateway makes. `litellm_credentials` picks an
#: endpoint from this, which is the one thing a generic provider never has to do.
CallKind = Literal["chat", "embedding"]

#: Credential form for the settings dialog. LiteLLM publishes a `hosted_vllm`
#: form, but it asks for a single `api_base` — which is exactly the assumption
#: that does not hold here, since chat and embeddings are separate deployments.
CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "api_base",
        "label": "Chat endpoint",
        "placeholder": "https://openrag-chat-predictor.openrag-models.svc.cluster.local:8443/v1",
        "tooltip": "URL of the InferenceService serving your chat model, ending in /v1. "
        "In-cluster this is the predictor Service; from a laptop it is an oc port-forward "
        "or a Route.",
        "required": True,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "embedding_api_base",
        "label": "Embeddings endpoint",
        "placeholder": "https://openrag-embed-predictor.openrag-models.svc.cluster.local:8443/v1",
        "tooltip": "URL of the InferenceService serving your embedding model, ending in /v1. "
        "vLLM serves one model per deployment, so this is a second InferenceService. Leave "
        "blank only if one endpoint serves both.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
    {
        "key": "api_key",
        "label": "ServiceAccount token",
        "placeholder": None,
        "tooltip": "A Kubernetes bearer token whose subject has `get` on inferenceservices in "
        "the model namespace, e.g. `oc create token openrag-inference -n openrag`. Both "
        "endpoints are authenticated with the same token.",
        "required": True,
        "field_type": "password",
        "options": None,
        "default_value": None,
    },
    {
        "key": "ssl_verify",
        "label": "TLS certificate authority",
        "placeholder": "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
        "tooltip": "Path to the CA bundle that signs the endpoint's certificate. In-cluster "
        "this is OpenShift's projected service CA. Set to `false` to skip verification — "
        "development only, for a port-forward whose certificate cannot match localhost.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
]

#: Fields an operator fills in that are not LiteLLM kwargs. The embedding
#: endpoint is selected *into* `api_base` per call; forwarding it as well would
#: land it in the request body, since LiteLLM passes kwargs it does not
#: recognise straight through.
_LOCAL_ONLY_FIELDS = frozenset({"embedding_api_base"})

#: LiteLLM kwargs that must not become request-body fields. `ssl_verify` is
#: read for TLS *and* — on the `hosted_vllm` chat path, verified against litellm
#: 1.84 with a capturing proxy — copied verbatim into the JSON sent to the
#: endpoint (`{"model": ..., "messages": ..., "ssl_verify": false}`). vLLM
#: ignores the unknown field; a stricter OpenAI-compatible server may 400 on
#: it, and either way a client TLS setting has no business on the wire.
#: `additional_drop_params` strips it from the body while leaving the TLS
#: effect intact, on chat, streaming and embeddings alike.
_BODY_DROP_PARAMS: tuple[str, ...] = ("ssl_verify",)

#: Values of `ssl_verify` that mean "do not verify". Spelled out rather than
#: parsed loosely: this switch turns off certificate checking, so an unrecognised
#: value must fail closed (be treated as a CA path) rather than open.
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})

#: TLS settings already reported. `resolve_ssl_verify` runs on every request, so
#: without this the "verification is disabled" warning — which has to be a
#: warning, since it is the one setting that silently weakens the deployment —
#: would be emitted once per chat message and per embedded chunk.
_reported_tls_settings: set[str] = set()


def _warn_once(setting: str, message: str, **fields: Any) -> None:
    """Report a TLS setting the first time this process sees it."""
    if setting in _reported_tls_settings:
        return
    _reported_tls_settings.add(setting)
    logger.warning(message, **fields)


def forget_tls_warnings() -> None:
    """Allow the TLS warnings to be emitted again. For tests."""
    _reported_tls_settings.clear()


#: The path segment every vLLM OpenAI endpoint is served under. Appended when an
#: operator pastes the Service URL without it — the single most common cause of
#: "works with curl, fails from OpenRAG", because curl was given the full path.
_API_SUFFIX = "/v1"


def normalized_api_base(value: Any) -> str:
    """An endpoint URL as LiteLLM needs it: no trailing slash, ending in `/v1`.

    Appends the suffix rather than rejecting the URL. An operator reads the
    predictor `Service` address off `oc get svc`, which has no path, and the
    alternative is a 404 from the endpoint's own router that says nothing about
    what is wrong.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if path.endswith(_API_SUFFIX) or f"{_API_SUFFIX}/" in f"{path}/":
        return raw
    normalized = urlunsplit((parts.scheme, parts.netloc, f"{path}{_API_SUFFIX}", "", ""))
    logger.debug(
        "Appended the OpenAI path to the OpenShift AI endpoint",
        original=raw,
        normalized=normalized,
    )
    return normalized


def resolve_ssl_verify(value: Any) -> bool | str:
    """The TLS setting for one endpoint: `True`, `False`, or a CA bundle path.

    Blank means "verify normally". A recognised false-y word disables
    verification. Anything else is taken as a filesystem path — including a path
    that does not exist, which is *warned about and passed through* so the call
    fails on the missing CA instead of quietly succeeding against the system
    trust store, which is not what the operator asked for.
    """
    raw = str(value if value is not None else "").strip()
    if not raw:
        return True
    lowered = raw.lower()
    if lowered in _FALSE_VALUES:
        _warn_once(
            "disabled",
            "TLS verification is disabled for OpenShift AI. This is a development-only "
            "setting for a port-forwarded endpoint; never use it on a deployed environment.",
        )
        return False
    if lowered in _TRUE_VALUES:
        return True

    import os

    if not os.path.exists(raw):
        _warn_once(
            f"missing:{raw}",
            "The OpenShift AI CA bundle path does not exist; TLS verification will fail "
            "until it does. In a pod the projected service CA is at "
            "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt.",
            path=raw,
        )
    return raw


def _values(stored: Mapping[str, Any] | None) -> dict[str, str]:
    """Stored form values, trimmed, with blanks dropped."""
    return {
        str(name): str(value).strip()
        for name, value in (stored or {}).items()
        if str(value or "").strip()
    }


def endpoints(stored: Mapping[str, Any] | None) -> tuple[str, str]:
    """`(chat_base, embedding_base)`, both normalized, either possibly empty.

    The embedding endpoint falls back to the chat one: a deployment that serves
    both from a single endpoint is unusual for `vLLM` but perfectly valid for
    another OpenAI-compatible gateway fronting the cluster, and it keeps the
    second field optional.
    """
    values = _values(stored)
    chat = normalized_api_base(values.get("api_base"))
    embedding = normalized_api_base(values.get("embedding_api_base")) or chat
    return chat, embedding


def ssl_verify_for(stored: Mapping[str, Any] | None) -> bool | str:
    """The TLS setting this module's own httpx calls should use.

    Model discovery and the health check talk to the endpoint directly rather
    than through LiteLLM, so without this they could fail on a certificate the
    gateway accepts, or the reverse.
    """
    return resolve_ssl_verify(_values(stored).get("ssl_verify"))


def litellm_credentials(stored: Mapping[str, Any], *, kind: CallKind = "chat") -> dict[str, Any]:
    """Stored form values as LiteLLM kwargs for `hosted_vllm`, for one call kind.

    This is the only place the two-endpoint shape collapses into the single
    `api_base` LiteLLM takes. `kind` is supplied by the gateway, the health check
    and the pre-save validator, so all three exercise the same endpoint the real
    traffic will.

    Returns nothing at all when no endpoint is configured. That is deliberate
    and not merely tidiness: LiteLLM falls back to `HOSTED_VLLM_API_BASE` from
    the process environment when `api_base` is absent, so handing it a bare
    `api_key` could send the cluster's ServiceAccount token to an unrelated host
    that happens to be configured there.
    """
    values = _values(stored)
    chat_base, embedding_base = endpoints(values)
    api_base = embedding_base if kind == "embedding" else chat_base
    if not api_base:
        return {}

    credentials: dict[str, Any] = {
        name: value
        for name, value in values.items()
        if name not in _LOCAL_ONLY_FIELDS and name not in {"api_base", "ssl_verify"}
    }
    credentials["api_base"] = api_base
    credentials["ssl_verify"] = resolve_ssl_verify(values.get("ssl_verify"))
    credentials["additional_drop_params"] = list(_BODY_DROP_PARAMS)
    return credentials


# --------------------------------------------------------------------------
# Model discovery
# --------------------------------------------------------------------------

#: How long a fetched model list is reused. The set of served models changes
#: when an administrator deploys an InferenceService, not per request.
MODELS_TTL_SECONDS = 300

#: Guard against a hung endpoint holding up a catalogue request. The catalogue
#: has a configured fallback, so failing fast is better than waiting.
MODELS_TIMEOUT_SECONDS = 10.0

#: Same, for the pre-save health check, which a human is waiting on.
HEALTH_TIMEOUT_SECONDS = 10.0

#: The listing path, relative to an `api_base` that already ends in `/v1`.
MODELS_PATH = "/models"


class ClusterModels(NamedTuple):
    chat: tuple[str, ...]
    embedding: tuple[str, ...]


_models_cache: dict[str, Any] = {"key": None, "at": 0.0, "value": None}


def cached_models() -> ClusterModels | None:
    """The last model list fetched from the cluster, if it is still fresh."""
    value = _models_cache["value"]
    if value is None or time.monotonic() - float(_models_cache["at"]) > MODELS_TTL_SECONDS:
        return None
    return value


def forget_models() -> None:
    """Drop the cached list. For tests and for a credential change."""
    _models_cache.update(key=None, at=0.0, value=None)


def _cache_key(stored: Mapping[str, Any] | None) -> str:
    """Identifies the endpoints and the token a cached list was fetched with."""
    values = _values(stored)
    chat, embedding = endpoints(values)
    return f"{chat}|{embedding}|{values.get('api_key', '')}"


def models_url(api_base: str) -> str:
    """The model-listing URL on `api_base`, however the operator typed it."""
    return f"{normalized_api_base(api_base)}{MODELS_PATH}"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _error_details(response: Any) -> str:
    """The concise error an OpenAI-compatible endpoint returned."""
    try:
        body = response.json()
    except (ValueError, TypeError):
        return str(getattr(response, "text", ""))[:500]
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or error.get("code") or "")[:500]
        return (
            str(body.get("message") or body.get("detail") or "")[:500]
            or str(getattr(response, "text", ""))[:500]
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
    """Retry endpoint reads without depending on API validation helpers.

    A `vLLM` pod that is still loading weights answers 503, and a `ModelCar`
    cold start takes minutes — so a single attempt would report a healthy
    deployment as broken during a rollout.
    """
    import httpx

    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
            if attempt == max_retries:
                raise error
        await asyncio.sleep(backoff_factor * (2**attempt))
    raise RuntimeError(f"OpenShift AI request to {url} failed after retries")


def model_ids(body: Any) -> tuple[str, ...]:
    """Model ids out of one OpenAI `GET /v1/models` body.

    Order is preserved and duplicates dropped. Anything that is not a list of
    objects with an `id` yields nothing, so a proxy answering with an error page
    empties this endpoint rather than putting garbage in a picker.
    """
    if not isinstance(body, Mapping):
        return ()
    data = body.get("data")
    if not isinstance(data, list):
        return ()
    ids: list[str] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        model_id = str(entry.get("id") or "").strip()
        if model_id and model_id not in ids:
            ids.append(model_id)
    return tuple(ids)


async def _list_models(client: Any, api_base: str, api_key: str) -> tuple[str, ...] | None:
    """The models one endpoint serves, or None if it could not be asked."""
    url = models_url(api_base)
    logger.debug("Listing models on the OpenShift AI endpoint", url=url)
    try:
        response = await _http_request_with_retry(
            "GET",
            url,
            client=client,
            headers=_auth_headers(api_key),
            timeout=MODELS_TIMEOUT_SECONDS,
        )
    except Exception as error:
        logger.warning(
            "Could not reach the OpenShift AI endpoint to list models",
            url=url,
            error=str(error),
        )
        return None
    if response.status_code != 200:
        logger.warning(
            "The OpenShift AI endpoint rejected the model listing",
            url=url,
            status_code=response.status_code,
            details=_error_details(response),
        )
        return None
    try:
        models = model_ids(response.json())
    except (ValueError, TypeError) as error:
        logger.warning(
            "The OpenShift AI endpoint returned a model listing that could not be read",
            url=url,
            error=str(error),
        )
        return None
    logger.debug("Listed models on the OpenShift AI endpoint", url=url, models=len(models))
    return models


async def fetch_models(credentials: Mapping[str, Any]) -> ClusterModels | None:
    """Ask each configured endpoint which models it actually serves.

    An `InferenceService` serves whatever its operator deployed, so this is the
    only truthful source for the pickers — LiteLLM's bundled table has no
    `hosted_vllm` models at all, and the `models:` rows in
    `model_providers.yaml` are the fallback for when the cluster cannot be
    reached.

    Chat and embedding are told apart by *which endpoint answered*, which needs
    no capability sniffing and cannot be wrong. When one endpoint serves both
    (no separate embedding URL), its ids go into both lists: `GET /v1/models`
    does not say what a model is for, and emptying a picker on a guess is worse
    than offering an id that fails loudly if it is picked for the wrong job.

    Returns None on any failure, so a catalogue request never fails because the
    cluster is unreachable; the caller keeps whatever it had.
    """
    import httpx

    values = _values(credentials)
    chat_base, embedding_base = endpoints(values)
    api_key = values.get("api_key", "")
    if not chat_base or not api_key:
        logger.warning(
            "Not listing models on OpenShift AI: credentials are incomplete. A chat endpoint "
            "and a ServiceAccount token are needed; the configured model list is used "
            "until then.",
            has_chat_endpoint=bool(chat_base),
            has_token=bool(api_key),
        )
        return None

    key = _cache_key(values)
    fresh = cached_models()
    if fresh is not None and _models_cache["key"] == key:
        return fresh

    logger.info(
        "Listing models on OpenShift AI",
        chat_endpoint=chat_base,
        embedding_endpoint=embedding_base,
        shared_endpoint=chat_base == embedding_base,
    )
    try:
        async with httpx.AsyncClient(
            verify=ssl_verify_for(values), timeout=MODELS_TIMEOUT_SECONDS
        ) as client:
            chat_models = await _list_models(client, chat_base, api_key)
            if chat_base == embedding_base:
                embedding_models = chat_models
            else:
                embedding_models = await _list_models(client, embedding_base, api_key)
    except Exception as error:
        logger.warning(
            "Could not list models on OpenShift AI; keeping the configured list",
            error=str(error),
        )
        return None

    models = ClusterModels(chat=chat_models or (), embedding=embedding_models or ())
    if not models.chat and not models.embedding:
        # Far more likely a listing we could not interpret than two endpoints
        # serving nothing. Emptying both pickers on that guess would be worse
        # than showing the fallback.
        logger.warning("OpenShift AI listed no usable models; keeping the configured list")
        return None

    _models_cache.update(key=key, at=time.monotonic(), value=models)
    logger.info(
        "Listed models on OpenShift AI",
        chat=len(models.chat),
        embedding=len(models.embedding),
    )
    return models


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


async def lightweight_health_check(credentials: Mapping[str, Any]) -> None:
    """Validate connectivity and the token without selecting a model.

    `GET /v1/models` needs no model, no prompt and no tokens billed, which is
    what makes it a check the provider can pass before anything has been chosen
    in Settings. Both endpoints are checked when they differ — an operator who
    got the embedding URL wrong should find out here, not on the first ingest.
    """
    import httpx

    values = _values(credentials)
    chat_base, embedding_base = endpoints(values)
    if not chat_base:
        raise Exception("No chat endpoint is configured for Red Hat OpenShift AI")
    api_key = values.get("api_key", "")
    if not api_key:
        raise Exception(
            "No ServiceAccount token is configured for Red Hat OpenShift AI. "
            "Create one with `oc create token <serviceaccount> -n <namespace>`."
        )

    targets = [("chat", chat_base)]
    if embedding_base and embedding_base != chat_base:
        targets.append(("embeddings", embedding_base))

    logger.info("Checking the OpenShift AI endpoints", endpoints=len(targets))
    try:
        async with httpx.AsyncClient(verify=ssl_verify_for(values)) as client:
            for label, api_base in targets:
                await _check_endpoint(client, label, api_base, api_key)
    except httpx.TimeoutException:
        logger.error("OpenShift AI health check timed out")
        raise Exception("The OpenShift AI endpoint did not respond in time") from None
    logger.info("OpenShift AI health check passed", endpoints=len(targets))


async def _check_endpoint(client: Any, label: str, api_base: str, api_key: str) -> None:
    """One endpoint's `GET /v1/models`, with a message that names the fix."""
    import httpx

    url = models_url(api_base)
    try:
        response = await _http_request_with_retry(
            "GET",
            url,
            client=client,
            headers=_auth_headers(api_key),
            timeout=HEALTH_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        raise
    except Exception as error:
        logger.error(
            "Could not reach the OpenShift AI endpoint",
            endpoint=label,
            url=url,
            error=str(error),
        )
        raise Exception(
            f"Could not reach the OpenShift AI {label} endpoint at {api_base}: {error}"
        ) from error

    if response.status_code == 200:
        logger.debug("OpenShift AI endpoint answered", endpoint=label, url=url)
        return

    details = _error_details(response)
    logger.error(
        "The OpenShift AI endpoint rejected the request",
        endpoint=label,
        url=url,
        status_code=response.status_code,
        details=details,
    )
    if response.status_code in (401, 403):
        raise Exception(
            f"The OpenShift AI {label} endpoint rejected the token. Check that its subject "
            "has `get` on inferenceservices in the model namespace, and that the token has "
            f"not expired. {details}".strip()
        )
    if response.status_code == 404:
        raise Exception(
            f"The OpenShift AI {label} endpoint has no /v1/models at {api_base}. Check the "
            f"URL points at the predictor Service and ends in /v1. {details}".strip()
        )
    raise Exception(
        f"The OpenShift AI {label} endpoint returned {response.status_code}: {details}".strip()
    )
