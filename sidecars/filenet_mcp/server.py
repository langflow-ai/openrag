"""HTTP entry point for the IBM Content Services MCP Server (FileNet P8).

The IBM package hardcodes ``mcp.run(transport="stdio")`` in every console
script, so OpenRAG consumes it as a *library*: this module mirrors the IBM
``_run_server()`` bootstrap sequence (GraphQL client -> MCP server ->
resources -> tools) and then serves the resulting FastMCP instance over
streamable HTTP, adding two OpenRAG-specific admin routes:

- ``GET /health``       process liveness (Kubernetes probe target).
- ``GET /diagnostics``  CPE reachability, ``TxeTextExtractAnnotation`` class
                        presence (Persistent Text Extract add-on check), and
                        ``isCBREnabled`` on the pinned document class.

Environment (IBM names at the container boundary):
    SERVER_URL      Content Services GraphQL URL. MUST NOT end with a slash:
                    the IBM client resolves relative ``downloadUrl`` values via
                    ``SERVER_URL.removesuffix("/graphql") + download_url``, and
                    a trailing slash silently turns every text fetch into an
                    error string returned *as document content* (Mode B).
    OBJECT_STORE    The single FileNet object store this process is bound to.
    USERNAME        CPD service account user (least-privilege, NOT an admin).
    PASSWORD        The account's actual password (CPD Basic auth; a Zen API
                    key is rejected by the gateway under Basic).
    SSL_ENABLED     Optional: "true"/"false" or a CA bundle path.
    FILENET_MCP_HOST / FILENET_MCP_PORT   Bind address (default 0.0.0.0:8811).
    FILENET_MCP_AUTH_TOKEN                Optional shared secret; when set,
                    every route except /health requires
                    ``Authorization: Bearer <token>``.
    FILENET_MCP_DOCUMENT_CLASS            Class checked by /diagnostics
                    (default "Document").
    FILENET_MCP_STARTUP_RETRIES / FILENET_MCP_STARTUP_DELAY_SECONDS
                    Bootstrap retry budget. The IBM bootstrap performs a live
                    GraphQL call, so a briefly-unreachable CPE must back off
                    rather than crash-loop.

The IBM imports are deliberately deferred into ``main()`` so that the pure
helpers in this module (env validation, auth check, diagnostics) can be unit
tested from the OpenRAG backend environment without the IBM package installed.

NOTE: this entry point leans on underscore-prefixed IBM internals
(``_initialize_mcp_server``). Pin the upstream git ref in
``Dockerfile.filenet-mcp`` and re-run the upgrade smoke check in
``README.md`` on every bump.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
import time
from collections.abc import Mapping
from typing import Any

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("filenet_mcp.server")

REQUIRED_ENV_VARS = ("SERVER_URL", "OBJECT_STORE", "USERNAME", "PASSWORD")

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - container bind address
DEFAULT_PORT = 8811
DEFAULT_DOCUMENT_CLASS = "Document"
DEFAULT_STARTUP_RETRIES = 30
DEFAULT_STARTUP_DELAY_SECONDS = 2.0
MAX_STARTUP_DELAY_SECONDS = 30.0

TXE_ANNOTATION_CLASS = "TxeTextExtractAnnotation"

TXE_CLASS_QUERY = (
    "query($os:String!){"
    ' classDescription(repositoryIdentifier:$os, identifier:"'
    + TXE_ANNOTATION_CLASS
    + '"){ id symbolicName } }'
)

CBR_FLAG_QUERY = (
    "query($os:String!,$c:String!){"
    " classDescription(repositoryIdentifier:$os, identifier:$c)"
    "{ symbolicName isCBREnabled } }"
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without the IBM package)
# ---------------------------------------------------------------------------


def validate_environment(env: Mapping[str, str]) -> list[str]:
    """Return a list of human-readable configuration errors (empty = valid)."""
    errors: list[str] = []
    for var in REQUIRED_ENV_VARS:
        if not env.get(var, "").strip():
            errors.append(f"Missing required environment variable: {var}.")

    server_url = env.get("SERVER_URL", "").strip()
    if server_url:
        if not server_url.startswith(("http://", "https://")):
            errors.append(f"SERVER_URL must start with http:// or https:// (got: {server_url!r}).")
        if server_url.endswith("/"):
            errors.append(
                "SERVER_URL must not end with a trailing slash: the IBM client "
                "resolves relative downloadUrl values by stripping a '/graphql' "
                "suffix, and a trailing slash silently breaks every text fetch "
                "(errors are returned as document content). Remove the trailing "
                f"slash from: {server_url!r}."
            )
    return errors


def get_port(env: Mapping[str, str]) -> int:
    """Resolve the HTTP bind port, falling back to the default on bad input."""
    raw = env.get("FILENET_MCP_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
        if not (0 < port < 65536):
            raise ValueError(f"port out of range: {port}")
        return port
    except ValueError as error:
        logger.warning(
            "Invalid FILENET_MCP_PORT value %r (%s); falling back to %d.",
            raw,
            error,
            DEFAULT_PORT,
        )
        return DEFAULT_PORT


def resolve_verify(env: Mapping[str, str]) -> bool | str:
    """Map SSL_ENABLED to an httpx ``verify`` value.

    "false"-like -> False, "true"-like/unset -> True, anything else is treated
    as a CA bundle path (the IBM ``*_SSL_ENABLED`` vars accept a path too).
    """
    raw = env.get("SSL_ENABLED", "true").strip()
    lowered = raw.lower()
    if lowered in ("false", "0", "no", "off"):
        return False
    if lowered in ("", "true", "1", "yes", "on"):
        return True
    return raw


def is_request_authorized(auth_header: str | None, expected_token: str) -> bool:
    """Check an ``Authorization`` header against the configured bearer token.

    An empty ``expected_token`` disables auth entirely (open sidecar).
    """
    if not expected_token:
        return True
    if not auth_header:
        return False
    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(value.strip(), expected_token)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests lacking the shared bearer token (except exempt paths)."""

    def __init__(self, app: Any, token: str, exempt_paths: tuple[str, ...] = ("/health",)):
        super().__init__(app)
        self.token = token
        self.exempt_paths = exempt_paths

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        if not is_request_authorized(request.headers.get("authorization"), self.token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Diagnostics (r1.6): CPE reachable? TXE add-on present? CBR enabled?
# ---------------------------------------------------------------------------


async def run_cpe_diagnostics(
    *,
    server_url: str,
    object_store: str,
    username: str,
    password: str,
    document_class: str = DEFAULT_DOCUMENT_CLASS,
    verify: bool | str = True,
    timeout: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Probe CPE GraphQL for availability, the TXE add-on, and the CBR flag.

    Never raises: every failure is folded into the returned payload so the
    caller (the /diagnostics route, and transitively the OpenRAG backend
    startup check) can log it without special-casing exceptions.
    """
    result: dict[str, Any] = {
        "cpe_reachable": False,
        "txe_annotation_class_present": None,
        "cbr_enabled": None,
        "object_store": object_store,
        "document_class": document_class,
        "errors": [],
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout, verify=verify)

    auth = (username, password)
    try:
        logger.info("Probing CPE GraphQL for the TXE annotation class...")
        try:
            response = await client.post(
                server_url,
                json={"query": TXE_CLASS_QUERY, "variables": {"os": object_store}},
                auth=auth,
            )
        except httpx.HTTPError as error:
            result["errors"].append(f"Failed to reach CPE GraphQL endpoint: {error}.")
            logger.warning("Failed to reach CPE GraphQL endpoint. Error: %s.", error)
            return result

        if response.status_code != 200:
            result["errors"].append(
                f"CPE GraphQL endpoint returned HTTP {response.status_code} "
                "for the TXE class probe (401/403 usually means bad service "
                "credentials; note Basic auth requires the account password, "
                "not a Zen API key)."
            )
            logger.warning("CPE GraphQL TXE probe failed. Status: %s.", response.status_code)
            return result

        result["cpe_reachable"] = True
        payload = _safe_json(response, result["errors"])
        if payload is not None:
            if payload.get("errors"):
                result["errors"].append(
                    f"CPE GraphQL reported errors for the TXE class probe: {payload['errors']}."
                )
                result["txe_annotation_class_present"] = False
            else:
                class_desc = (payload.get("data") or {}).get("classDescription")
                result["txe_annotation_class_present"] = bool(class_desc)
        logger.info(
            "Successfully probed the TXE annotation class. Present: %s.",
            result["txe_annotation_class_present"],
        )

        logger.info("Probing CPE GraphQL for isCBREnabled on class %r...", document_class)
        try:
            response = await client.post(
                server_url,
                json={
                    "query": CBR_FLAG_QUERY,
                    "variables": {"os": object_store, "c": document_class},
                },
                auth=auth,
            )
        except httpx.HTTPError as error:
            result["errors"].append(f"Failed to run the CBR flag probe: {error}.")
            logger.warning("Failed to run the CBR flag probe. Error: %s.", error)
            return result

        if response.status_code != 200:
            result["errors"].append(
                f"CPE GraphQL endpoint returned HTTP {response.status_code} for the CBR flag probe."
            )
            return result

        payload = _safe_json(response, result["errors"])
        if payload is not None:
            if payload.get("errors"):
                result["errors"].append(
                    f"CPE GraphQL reported errors for the CBR flag probe: {payload['errors']}."
                )
            else:
                class_desc = (payload.get("data") or {}).get("classDescription") or {}
                is_cbr = class_desc.get("isCBREnabled")
                result["cbr_enabled"] = bool(is_cbr) if is_cbr is not None else None
        logger.info(
            "Successfully probed isCBREnabled. Class: %r, enabled: %s.",
            document_class,
            result["cbr_enabled"],
        )
        return result
    except Exception as error:  # defensive: diagnostics must never raise
        result["errors"].append(f"Unexpected diagnostics failure: {error}.")
        logger.exception("Unexpected diagnostics failure.")
        return result
    finally:
        if owns_client:
            await client.aclose()


def _safe_json(response: httpx.Response, errors: list[str]) -> dict[str, Any] | None:
    """Parse a JSON body, recording (not raising) parse failures."""
    try:
        payload = response.json()
    except ValueError as error:
        errors.append(f"CPE GraphQL returned a non-JSON body: {error}.")
        return None
    if not isinstance(payload, dict):
        errors.append("CPE GraphQL returned an unexpected non-object JSON body.")
        return None
    return payload


# ---------------------------------------------------------------------------
# IBM server bootstrap + HTTP serving
# ---------------------------------------------------------------------------


def _bootstrap_ibm_server() -> Any:
    """Mirror IBM's ``_run_server()`` bootstrap, returning the FastMCP instance.

    Mirrors ``cs_mcp_server.mcp_server_main`` as of the ref pinned in
    ``Dockerfile.filenet-mcp`` (ServerType.CORE — the only config that
    registers ``document_search`` + ``get_document_text_extract``). Verify
    these call signatures on every ref bump.
    """
    from cs_mcp_server import mcp_server_main as ibm

    server_type = ibm.ServerType.CORE
    logger.info("Initializing the IBM Content Services GraphQL client...")
    graphql_client = ibm.initialize_graphql_client()
    logger.info("Successfully initialized the GraphQL client.")

    logger.info("Initializing the IBM MCP server (type: %s)...", server_type)
    ibm._initialize_mcp_server(server_type)
    metadata_cache = ibm.MetadataCache()
    ibm.register_server_resources(graphql_client, server_type)
    ibm.register_server_tools(graphql_client, metadata_cache, server_type)
    logger.info("Successfully registered IBM MCP server resources and tools.")

    if ibm.mcp is None:  # pragma: no cover - upstream contract violation
        raise RuntimeError(
            "IBM _initialize_mcp_server() did not populate the module-level "
            "'mcp' instance; the pinned upstream ref is incompatible with "
            "this entry point."
        )
    return ibm.mcp


def _bootstrap_with_retry(retries: int, base_delay: float) -> Any:
    """Retry the IBM bootstrap with capped exponential backoff.

    The IBM bootstrap performs a live GraphQL call (dynamic resource listing),
    so a temporarily unreachable CPE must not crash-loop the sidecar.
    """
    attempt = 0
    while True:
        attempt += 1
        logger.info("Bootstrapping the IBM MCP server (attempt %d/%d)...", attempt, retries)
        try:
            mcp = _bootstrap_ibm_server()
            logger.info("Successfully bootstrapped the IBM MCP server.")
            return mcp
        except Exception as error:
            if attempt >= retries:
                logger.error(
                    "Failed to bootstrap the IBM MCP server after %d attempts. Error: %s.",
                    attempt,
                    error,
                )
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), MAX_STARTUP_DELAY_SECONDS)
            logger.warning(
                "Failed to bootstrap the IBM MCP server (attempt %d/%d); CPE may "
                "be unreachable. Retrying in %.1fs. Error: %s.",
                attempt,
                retries,
                delay,
                error,
            )
            time.sleep(delay)


def _register_admin_routes(mcp: Any, env: Mapping[str, str]) -> None:
    """Attach the OpenRAG /health and /diagnostics routes to the FastMCP app."""
    object_store = env.get("OBJECT_STORE", "").strip()
    document_class = env.get("FILENET_MCP_DOCUMENT_CLASS", DEFAULT_DOCUMENT_CLASS).strip()

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "object_store": object_store})

    @mcp.custom_route("/diagnostics", methods=["GET"])
    async def diagnostics(_request: Request) -> JSONResponse:
        result = await run_cpe_diagnostics(
            server_url=env.get("SERVER_URL", "").strip(),
            object_store=object_store,
            username=env.get("USERNAME", ""),
            password=env.get("PASSWORD", ""),
            document_class=document_class or DEFAULT_DOCUMENT_CLASS,
            verify=resolve_verify(env),
        )
        return JSONResponse(result)


def _get_env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s value %r; falling back to %d.", name, raw, default)
        return default


def _get_env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s value %r; falling back to %.1f.", name, raw, default)
        return default


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info("Validating the FileNet P8 MCP sidecar environment...")
    errors = validate_environment(os.environ)
    if errors:
        for error in errors:
            logger.error("Configuration error: %s", error)
        logger.error("Failed to validate the sidecar environment; exiting.")
        sys.exit(1)
    logger.info("Successfully validated the sidecar environment.")

    retries = _get_env_int(os.environ, "FILENET_MCP_STARTUP_RETRIES", DEFAULT_STARTUP_RETRIES)
    base_delay = _get_env_float(
        os.environ, "FILENET_MCP_STARTUP_DELAY_SECONDS", DEFAULT_STARTUP_DELAY_SECONDS
    )
    mcp = _bootstrap_with_retry(max(1, retries), max(0.1, base_delay))

    _register_admin_routes(mcp, os.environ)

    app = mcp.http_app()
    token = os.environ.get("FILENET_MCP_AUTH_TOKEN", "").strip()
    if token:
        logger.info("Bearer-token authentication is ENABLED for the sidecar.")
        app.add_middleware(BearerTokenMiddleware, token=token)
    else:
        logger.info("Bearer-token authentication is DISABLED (FILENET_MCP_AUTH_TOKEN unset).")

    host = os.environ.get("FILENET_MCP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = get_port(os.environ)
    logger.info(
        "Starting the FileNet P8 MCP sidecar on %s:%d (object store: %s)...",
        host,
        port,
        os.environ.get("OBJECT_STORE", ""),
    )

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
