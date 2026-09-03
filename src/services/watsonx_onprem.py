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
  the SaaS provider's `project_id` may be a deployment `space_id` or absent
  entirely — the watsonx.ai lightweight engine has neither (it "does not use
  projects"). See `install_litellm_compatibility` for what that costs.
- **Models are whatever the operator deployed**, so the catalogue ids come from
  `config/model_providers.yaml` rather than LiteLLM's IBM Cloud price table.

The provider key is OpenRAG's own; `LITELLM_PROVIDER` is what it routes as.
Nothing here imports OpenRAG config — `config_manager`, `model_catalog` and
`llm_gateway` all read this module, so it has to stay a leaf.

TLS: trusting a cluster's own CA
--------------------------------
A CPD cluster is usually fronted by an internal or self-signed CA, and the call
then fails before it leaves the process::

    litellm.InternalServerError: WatsonxException - Cannot connect to host
    <cluster>:443 ssl:True [SSLCertVerificationError: ... certificate verify
    failed: self-signed certificate in certificate chain]

There is no per-provider setting for this, and no OpenRAG one either. LiteLLM
resolves TLS trust from process-wide environment only — verified against
litellm 1.84 with a self-signed server, chat and embeddings both:

- ``SSL_CERT_FILE=<path>``   works. **This is the fix.**
- ``SSL_VERIFY=false``       works, but turns verification off for *every*
  provider in the process, OpenAI and Anthropic included. Development only.
- ``ssl_verify=False`` as a per-call kwarg does **not** work: litellm threads it
  through only some providers, and watsonx is not one of them. It is silently
  ignored, so do not reach for it.

``SSL_CERT_FILE`` *replaces* certifi's roots rather than adding to them, so
pointing it at the cluster CA alone breaks every public provider. Concatenate::

    cat "$(python -m certifi)" cluster-ca.crt > /etc/ssl/certs/openrag-ca.pem
    export SSL_CERT_FILE=/etc/ssl/certs/openrag-ca.pem

In Kubernetes, mount the cluster CA into the backend pod and build that bundle
in the entrypoint; the operator's ConfigMap is the usual home for the CA. A
failure that gets this far is reported by the gateway as a trust problem rather
than as an outage — see ``_UPSTREAM_TLS_MESSAGE`` in ``services/llm_gateway``.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

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
        "tooltip": "Your Cloud Pak for Data username. Combined with the API key below "
        "into the ZenApiKey the cluster authenticates with.",
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
        "tooltip": "Optional. The deployment space the models are served from. Leave blank "
        "on a lightweight-engine install, which uses neither spaces nor projects.",
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
]

#: Fields an operator fills in that are not LiteLLM kwargs. `username` is half
#: of the Zen key and nothing else — forwarding it would land it in the request
#: body, since LiteLLM passes kwargs it does not recognise straight through.
_LOCAL_ONLY_FIELDS = frozenset({"username"})


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


def litellm_credentials(stored: Mapping[str, Any]) -> dict[str, str]:
    """Stored form values as LiteLLM kwargs for `watsonx`.

    `api_key` is set to the Zen key as well as `zen_api_key`: the embeddings
    path rejects the call before it ever reads the auth header if `api_key` is
    unset, and the header it then builds comes from `zen_api_key`, so the two
    have to travel together.
    """
    values = {
        str(name): str(value).strip()
        for name, value in (stored or {}).items()
        if str(value or "").strip()
    }
    zen = values.get("zen_api_key") or zen_api_key(values.get("username"), values.get("api_key"))

    credentials = {
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
    """The `Authorization` value for OpenRAG's own calls to the cluster.

    The health check talks to `/ml/v1` directly rather than through LiteLLM, so
    it has to build the same header LiteLLM would.
    """
    credentials = litellm_credentials(stored)
    if credentials.get("zen_api_key"):
        return f"ZenApiKey {credentials['zen_api_key']}"
    if credentials.get("api_key"):
        return f"Bearer {credentials['api_key']}"
    return ""


def model_specs_url(api_base: str) -> str:
    """The catalogue URL on `api_base`, however the operator typed the cluster URL."""
    return f"{(api_base or '').rstrip('/')}{MODEL_SPECS_PATH}?version={API_VERSION}"


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
            module = __import__(module_name, fromlist=["_get_api_params"])
        except Exception:
            continue
        current = getattr(module, "_get_api_params", None)
        if current is None or getattr(current, _PATCH_MARKER, False):
            continue
        module._get_api_params = _get_api_params_allowing_no_scope
        patched.append(module_name)

    mixin = common_utils.IBMWatsonXMixin
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
