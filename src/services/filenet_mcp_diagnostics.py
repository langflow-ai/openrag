"""Startup diagnostics for the FileNet P8 MCP chat tool (non-blocking).

Probes the FileNet MCP sidecar's OpenRAG admin routes and logs the outcome:

- ``GET /health``       — is the sidecar process up?
- ``GET /diagnostics``  — sidecar-side CPE probes: GraphQL reachable, the
  ``TxeTextExtractAnnotation`` class present (Persistent Text Extract add-on),
  and ``isCBREnabled`` on the pinned document class.

The CPE credentials live only in the sidecar's environment, so the checks run
there; the backend merely fetches and interprets the result. Every outcome is
a log line (INFO when healthy, WARNING when degraded) — a failed diagnostic
NEVER blocks or fails backend startup. Ongoing availability is owned by the
sidecar's Kubernetes probes; this is a startup-time operator signal.
"""

from urllib.parse import urlparse

import httpx

from config.settings import get_filenet_mcp_token, get_filenet_mcp_url
from utils.logging_config import get_logger

logger = get_logger(__name__)

DIAGNOSTICS_TIMEOUT_SECONDS = 10.0


def derive_admin_url(mcp_url: str, path: str) -> str:
    """Derive a sidecar admin-route URL from the MCP endpoint URL.

    ``OPENRAG_FILENET_MCP_URL`` points at the streamable-HTTP MCP endpoint
    (e.g. ``http://filenet-mcp:8811/mcp``); the admin routes live at the
    server root (e.g. ``http://filenet-mcp:8811/health``).
    """
    parsed = urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


async def run_filenet_startup_diagnostics(
    http_client: httpx.AsyncClient | None = None,
) -> dict | None:
    """Probe the FileNet MCP sidecar and log the health of the retrieval path.

    Returns the sidecar's diagnostics payload when it was retrieved (possibly
    reporting a degraded state), or ``None`` when the sidecar itself could not
    be reached or answered abnormally. Never raises.
    """
    mcp_url = get_filenet_mcp_url()
    if not mcp_url:
        # Callers gate on availability already; this is a defensive backstop.
        logger.debug("FileNet MCP URL not configured; skipping diagnostics")
        return None

    health_url = derive_admin_url(mcp_url, "/health")
    diagnostics_url = derive_admin_url(mcp_url, "/diagnostics")
    headers: dict[str, str] = {}
    token = get_filenet_mcp_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=DIAGNOSTICS_TIMEOUT_SECONDS)
    try:
        logger.info("Running FileNet P8 MCP startup diagnostics", sidecar_url=health_url)
        try:
            response = await client.get(health_url)
        except httpx.HTTPError as error:
            logger.warning(
                "FileNet P8 MCP sidecar is unreachable — the FileNet chat tool "
                "will fail at query time until the sidecar is up",
                sidecar_url=health_url,
                error=str(error),
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "FileNet P8 MCP sidecar health check returned a non-200 status",
                sidecar_url=health_url,
                status_code=response.status_code,
            )
            return None

        try:
            response = await client.get(diagnostics_url, headers=headers)
        except httpx.HTTPError as error:
            logger.warning(
                "FileNet P8 MCP sidecar diagnostics request failed",
                sidecar_url=diagnostics_url,
                error=str(error),
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "FileNet P8 MCP sidecar diagnostics returned a non-200 status "
                "(401 usually means OPENRAG_FILENET_MCP_TOKEN does not match "
                "the sidecar's FILENET_MCP_AUTH_TOKEN)",
                sidecar_url=diagnostics_url,
                status_code=response.status_code,
            )
            return None

        try:
            payload = response.json()
        except ValueError as error:
            logger.warning(
                "FileNet P8 MCP sidecar diagnostics returned a non-JSON body",
                sidecar_url=diagnostics_url,
                error=str(error),
            )
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "FileNet P8 MCP sidecar diagnostics returned an unexpected body shape",
                sidecar_url=diagnostics_url,
            )
            return None

        _log_diagnostics_payload(payload)
        return payload
    except Exception as error:  # defensive: diagnostics must never break startup
        logger.warning(
            "FileNet P8 MCP startup diagnostics failed unexpectedly",
            error=str(error),
        )
        return None
    finally:
        if owns_client:
            await client.aclose()


def _log_diagnostics_payload(payload: dict) -> None:
    """Translate the sidecar's diagnostics payload into operator log lines."""
    cpe_reachable = payload.get("cpe_reachable")
    txe_present = payload.get("txe_annotation_class_present")
    cbr_enabled = payload.get("cbr_enabled")
    object_store = payload.get("object_store")
    document_class = payload.get("document_class")
    errors = payload.get("errors") or []

    degraded = False
    if not cpe_reachable:
        degraded = True
        logger.warning(
            "FileNet P8 CPE GraphQL endpoint is not reachable (or rejected the "
            "service credentials) from the MCP sidecar — FileNet search will "
            "return no results",
            object_store=object_store,
            errors=errors,
        )
    if txe_present is False:
        degraded = True
        logger.warning(
            "FileNet P8 'Persistent Text Extract' add-on not detected "
            "(TxeTextExtractAnnotation class missing) — FileNet search degrades "
            "to metadata-only: no document text, no citations",
            object_store=object_store,
        )
    elif txe_present is None and cpe_reachable:
        degraded = True
        logger.warning(
            "FileNet P8 'Persistent Text Extract' status could not be determined",
            object_store=object_store,
            errors=errors,
        )
    if cbr_enabled is False:
        degraded = True
        logger.warning(
            "FileNet P8 content-based retrieval (CBR) is disabled on the pinned "
            "document class — document_search will fail for it",
            object_store=object_store,
            document_class=document_class,
        )

    if not degraded:
        logger.info(
            "FileNet P8 MCP diagnostics passed",
            object_store=object_store,
            document_class=document_class,
            cpe_reachable=True,
            txe_annotation_class_present=txe_present,
            cbr_enabled=cbr_enabled,
        )
