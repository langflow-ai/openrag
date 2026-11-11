"""Oracle Cloud Infrastructure Generative AI - LiteLLM's own `oci` provider.

There is no new transport and the key is LiteLLM's, so no route alias. The module
exists for what a bare `model_providers.yaml` row would get wrong:

- **The form.** LiteLLM's published OCI form marks all six API-key fields
  required, so an instance or workload principal (no keys at all) could never be
  "configured". Here only region and compartment are required, and the auth
  method is one more stored field, because the generic forms have no selector.
- **Principals.** The OCI SDK signer is not JSON-serializable, so it is built in
  `litellm_runtime_kwargs`, which the gateway calls at each LiteLLM boundary. It
  never enters the stored credentials, the health-cache key or a log line.
- **A model-free health check.** Polls never run inference.

Field names are LiteLLM's own kwargs, except `oci_auth_method`, which only this
module reads.

Nothing here imports OpenRAG config - `config_manager`, `model_catalog` and
`llm_gateway` all read this module, so it has to stay a leaf.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Mapping
from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

PROVIDER_KEY = "oci"

DEFAULT_AUTH_METHOD = "api_key"
_SHARED_FIELDS = frozenset({"oci_region", "oci_compartment_id"})
_API_KEY_FIELDS = frozenset({"oci_user", "oci_fingerprint", "oci_tenancy", "oci_key"})
#: Fields each auth method sends to LiteLLM. A principal never sees leftover
#: API-key fields from an earlier configuration.
AUTH_METHODS: dict[str, frozenset[str]] = {
    "api_key": _API_KEY_FIELDS,
    "instance_principal": frozenset(),
    "workload_identity": frozenset(),
}


def _field(
    key: str, label: str, *, required: bool = False, field_type: str = "text", **extra: Any
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "placeholder": None,
        "tooltip": None,
        "required": required,
        "field_type": field_type,
        "options": None,
        "default_value": None,
        **extra,
    }


_API_KEY_ONLY = "Only for the api_key auth method."

CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    _field("oci_region", "Region", required=True, placeholder="us-chicago-1"),
    _field(
        "oci_compartment_id",
        "Compartment OCID",
        required=True,
        placeholder="ocid1.compartment.oc1...",
    ),
    _field(
        "oci_auth_method",
        "Auth method",
        placeholder=DEFAULT_AUTH_METHOD,
        tooltip="Type api_key, instance_principal or workload_identity.",
    ),
    _field("oci_user", "User OCID", tooltip=_API_KEY_ONLY),
    _field("oci_fingerprint", "API key fingerprint", tooltip=_API_KEY_ONLY),
    _field("oci_tenancy", "Tenancy OCID", tooltip=_API_KEY_ONLY),
    _field("oci_key", "Private key (PEM)", field_type="textarea", tooltip=_API_KEY_ONLY),
]

#: One signer per method lives for the process; `litellm_runtime_kwargs` refreshes
#: its token before each hand-over (see `_refresh`).
_signers: dict[str, Any] = {}
#: A failed build is remembered briefly, so a host without the identity does not
#: pay the SDK's network attempts on every request, yet recovers quickly.
_FAILURE_TTL_SECONDS = 30
_failures: dict[str, tuple[float, str]] = {}
_signer_lock = threading.Lock()


def _clean(stored: Mapping[str, Any] | None) -> dict[str, str]:
    return {k: v.strip() for k, v in (stored or {}).items() if isinstance(v, str) and v.strip()}


def _auth_method(values: Mapping[str, str]) -> str:
    method = values.get("oci_auth_method", DEFAULT_AUTH_METHOD).lower()
    if method not in AUTH_METHODS:
        raise ValueError(
            f"Unknown OCI auth method {method!r}. Use one of: {', '.join(AUTH_METHODS)}"
        )
    return method


def litellm_credentials(stored: Mapping[str, Any]) -> dict[str, str]:
    """The stored values valid for the chosen auth method, under LiteLLM's names."""
    values = _clean(stored)
    allowed = _SHARED_FIELDS | AUTH_METHODS[_auth_method(values)]
    return {k: v for k, v in values.items() if k in allowed}


def litellm_runtime_kwargs(stored: Mapping[str, Any]) -> dict[str, Any]:
    """The SDK signer for the two principal methods; nothing for api_key."""
    method = _auth_method(_clean(stored))
    if method == DEFAULT_AUTH_METHOD:
        return {}
    signer = _signer(method)
    _refresh(method, signer)
    return {"oci_signer": signer}


def _refresh(method: str, signer: Any) -> None:
    """Renew the signer's session token if it is due.

    LiteLLM signs with `do_request_sign`, which skips the refresh the SDK does in
    `signer.__call__` and on a 401 retry, so a cached signer would keep the token
    it was built with and fail every call once that expires. Both calls are cheap
    no-ops while the token is valid and are serialised by the SDK's own locks.
    """
    try:
        if hasattr(signer, "get_security_token"):
            signer.get_security_token()
        else:
            # Instance principal: the private method its own `__call__` runs.
            signer._reset_signers()
    except Exception as exc:
        logger.warning("OCI token refresh failed", auth_method=method, error=str(exc))
        raise ValueError(
            f"Could not refresh the OCI {method} security token ({type(exc).__name__})"
        ) from None


def _signer(method: str) -> Any:
    if method in _signers:
        return _signers[method]
    # Building can block for seconds on an unreachable IMDS. Callers run in pool
    # threads, so a second caller fails fast instead of parking another thread.
    if not _signer_lock.acquire(blocking=False):
        raise ValueError(f"The OCI {method} signer is still being set up. Retry shortly.")
    try:
        if method in _signers:
            return _signers[method]
        failed_at, message = _failures.get(method, (0.0, ""))
        if time.monotonic() - failed_at < _FAILURE_TTL_SECONDS:
            raise ValueError(message)
        try:
            _signers[method] = _build_signer(method)
        except ValueError as exc:
            _failures[method] = (time.monotonic(), str(exc))
            raise
        return _signers[method]
    finally:
        _signer_lock.release()


def _bounded_retry() -> Any:
    """The SDK's own default gives up on an unreachable IMDS after about 90 seconds.

    The signer keeps this strategy for its later token refreshes too.
    """
    import oci

    return oci.retry.RetryStrategyBuilder(
        max_attempts_check=True,
        max_attempts=2,
        total_elapsed_time_check=True,
        total_elapsed_time_seconds=10,
        retry_max_wait_between_calls_seconds=2,
        service_error_check=True,
        service_error_retry_config={-1: [], 429: [], 404: []},
        service_error_retry_on_any_5xx=True,
    ).get_retry_strategy()


def _build_signer(method: str) -> Any:
    try:
        from oci.auth import signers
    except ImportError:
        raise ValueError(
            f"The 'oci' package is required for OCI {method} auth but is not installed "
            "(install the `oci` extra: `uv sync --extra oci` or `pip install 'openrag[oci]'`)"
        ) from None
    try:
        retry = _bounded_retry()
        if method == "instance_principal":
            return signers.InstancePrincipalsSecurityTokenSigner(
                retry_strategy=retry, federation_client_retry_strategy=retry
            )
        return signers.get_oke_workload_identity_resource_principal_signer(retry_strategy=retry)
    except Exception as exc:
        # IMDS and proxymux errors carry no secrets; the operator needs them.
        logger.warning("OCI signer build failed", auth_method=method, error=str(exc))
        raise ValueError(_signer_failure(method, exc)) from None


def _signer_failure(method: str, exc: Exception) -> str:
    if method == "instance_principal":
        need = (
            "Instance principal auth needs OpenRAG to run on an OCI Compute instance in a dynamic group "
            "with a policy such as 'allow dynamic-group <name> to use generative-ai-family in compartment "
            "<compartment>'."
        )
    else:
        need = (
            "Workload identity auth needs an OKE cluster with workload identity enabled and a service "
            "account configured for it (KUBERNETES_SERVICE_HOST and OCI_RESOURCE_PRINCIPAL_REGION "
            "must be set in the pod)."
        )
    return f"Could not build the OCI {method} signer ({type(exc).__name__}). {need}"


async def lightweight_health_check(credentials: Mapping[str, Any]) -> None:
    """Validate the configuration without selecting a model or calling inference.

    Failures are `ValueError`s naming what is wrong, never echoing a value.
    """
    values = _clean(credentials)
    method = _auth_method(values)
    required = sorted(_SHARED_FIELDS | AUTH_METHODS[method])
    if missing := [name for name in required if name not in values]:
        raise ValueError(f"Missing OCI settings for {method} auth: {', '.join(missing)}")
    if method == DEFAULT_AUTH_METHOD:
        _check_pem(values["oci_key"])
    else:
        await asyncio.to_thread(_signer, method)
    logger.info("OCI Generative AI health check passed", auth_method=method)


def _check_pem(pem: str) -> None:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    # LiteLLM accepts literal "\n" in a single-line paste, so the check does too.
    data = pem.replace("\\n", "\n").replace("\r\n", "\n").encode()
    try:
        if not isinstance(load_pem_private_key(data, password=None), RSAPrivateKey):
            raise TypeError("OCI API keys are RSA")
    except Exception:
        raise ValueError(
            "The OCI private key is not a valid unencrypted RSA PEM private key. Paste the whole file, "
            "including the BEGIN and END lines."
        ) from None
