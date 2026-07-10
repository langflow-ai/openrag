"""Builds an OCI SDK Signer object for the two non-API-key auth methods.

litellm's OCI Generative AI integration (litellm/llms/oci/common_utils.py,
already an OpenRAG dependency) natively accepts a pre-built OCI SDK Signer
object via the ``oci_signer`` call-time kwarg -- if present, it calls
``oci_signer.do_request_sign(request, enforce_content_headers=True)``
directly instead of using the manual user/fingerprint/tenancy/key signing
path. That is the integration point this module targets: build the right
signer once per call, hand it to litellm, and let litellm's existing,
already-shipped OCI request-signing logic do the rest.

Verified against the real OCI Python SDK source (oracle/oci-python-sdk):
  - ``oci.auth.signers.InstancePrincipalsSecurityTokenSigner()`` takes no
    required arguments; it auto-detects identity via the OCI instance
    metadata service (IMDS) and raises if not running on OCI Compute.
  - ``oci.auth.signers.get_oke_workload_identity_resource_principal_signer()``
    also takes no required arguments in the common case; it auto-detects
    via the ``KUBERNETES_SERVICE_HOST`` env var (standard K8s-injected) and
    the default Kubernetes projected service-account token path. It
    requires the OKE cluster to have Workload Identity enabled and the
    pod's service account configured for it -- an operator-side
    prerequisite this function cannot satisfy or detect in advance.
"""

from __future__ import annotations

from typing import Any


class OCISignerConstructionError(Exception):
    """Raised when constructing an OCI SDK signer for a non-api_key
    auth_method fails. Wraps the underlying OCI SDK exception with an
    actionable message naming the concrete unmet prerequisite, instead of
    letting the raw SDK exception (which rarely names the fix) propagate."""


def build_oci_signer(auth_method: str) -> Any | None:
    """Build an OCI SDK Signer for ``auth_method``.

    Returns None for "api_key" -- callers should fall through to the
    existing manual user/fingerprint/tenancy/key credential path in that
    case (see utils.embedding_kwargs.oci_credential_kwargs).

    Raises OCISignerConstructionError if a non-"api_key" method's signer
    construction fails (e.g. not running on OCI Compute for
    instance_principal, or the OKE cluster doesn't have Workload Identity
    enabled for workload_identity).

    Raises ValueError if auth_method isn't one of the three known values.
    """
    if auth_method == "api_key":
        return None

    if auth_method == "instance_principal":
        import oci.auth.signers

        try:
            return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        except Exception as e:
            raise OCISignerConstructionError(
                "Failed to construct an OCI Instance Principal signer: "
                f"{e}. Instance Principal auth requires running on an OCI "
                "Compute instance with a dynamic group matching the "
                "instance, and a policy granting that dynamic group access "
                "to the target compartment's generative-ai-family "
                "resources (e.g. 'allow dynamic-group <name> to use "
                "generative-ai-family in compartment <compartment>')."
            ) from e

    if auth_method == "workload_identity":
        import oci.auth.signers

        try:
            return oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
        except Exception as e:
            raise OCISignerConstructionError(
                "Failed to construct an OCI OKE Workload Identity signer: "
                f"{e}. Workload Identity auth requires the OKE cluster to "
                "have Workload Identity enabled and this pod's service "
                "account to be configured for it. See: "
                "https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/"
                "contenggrantingworkloadaccesstoresources.htm"
            ) from e

    raise ValueError(
        f"Unknown OCI auth_method: {auth_method!r}. Expected one of "
        "'api_key', 'instance_principal', 'workload_identity'."
    )
