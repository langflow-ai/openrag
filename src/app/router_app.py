"""Standalone Langflow proxy router.

A deliberately tiny FastAPI/uvicorn app that exposes ONLY the Langflow ingest
callback endpoint and the OpenAI-compatible LLM paths Langflow needs, then
forwards them to the real backend. It runs in the same process as the main
backend (a daemon thread on its own port) when ``OPENRAG_BACKEND_ROUTER_ENABLE``
is set, so Langflow's reachable surface is an explicit allowlist rather than
the full backend internal API.

It is a thin reverse proxy only — it does NOT validate the ingest JWT; the real
backend still does. Its sole job is network-surface isolation.
"""

from __future__ import annotations

import ipaddress
import re
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from app.middleware import RequestLoggingMiddleware
from config.settings import (
    ACCESS_LOG_ENABLED,
    INGEST_CALLBACK_PATH,
    LANGFLOW_CONNECT_TIMEOUT,
    LANGFLOW_TIMEOUT,
    OPENRAG_BACKEND_ROUTER_HOST,
    OPENRAG_BACKEND_ROUTER_PORT,
    OPENRAG_BACKEND_ROUTER_UPSTREAM_URL,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Validate the configured upstream before creating routes that forward credentials.
_UPSTREAM_ENV_VAR = "OPENRAG_BACKEND_ROUTER_UPSTREAM_URL"
_HOST_LABEL_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# Deliberately exact private paths: Langflow gets an unversioned internal
# interface, while the router maps each one to the backend's public /v1 API.
# Do not proxy arbitrary paths. This app runs on a separate port from FastMCP;
# the mapping ensures neither /mcp nor any public /v1 path is exposed here.
_LLM_PROXY_UPSTREAM_PATHS = {
    "/models": "/v1/models",
    "/chat/completions": "/v1/chat/completions",
    "/embeddings": "/v1/embeddings",
}

# Only these request headers are forwarded upstream; everything else (Host,
# hop-by-hop headers, etc.) is dropped so the router cannot be abused as an open
# proxy. The ingest token travels in either Authorization or the custom header.
_FORWARDED_HEADERS = ("authorization", "x-openrag-ingest-token", "content-type", "accept")
_INGEST_UPSTREAM_TIMEOUT = httpx.Timeout(60.0)
_LLM_UPSTREAM_TIMEOUT = httpx.Timeout(
    timeout=LANGFLOW_TIMEOUT,
    connect=LANGFLOW_CONNECT_TIMEOUT,
    read=LANGFLOW_TIMEOUT,
    write=LANGFLOW_CONNECT_TIMEOUT,
    pool=LANGFLOW_CONNECT_TIMEOUT,
)


def _validate_upstream_base_url(value: str) -> str:
    """Validate and normalize the base URL that receives forwarded credentials.

    HTTPS is required for remote upstreams. Plain HTTP is only permitted for
    the explicit loopback hosts used by local development.
    """
    message = f"Invalid {_UPSTREAM_ENV_VAR}: expected an HTTPS host or HTTP loopback URL"
    if not value or value != value.strip() or "?" in value or "#" in value:
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port
    except ValueError as error:
        raise ValueError(message) from error

    if (
        parts.scheme.lower() not in {"http", "https"}
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(message)

    # urlsplit may accept junk after a bracketed IPv6 literal as part of the
    # authority on some Python versions (for example ``[::1]evil.example``).
    # Check the authority grammar explicitly before trusting ``hostname``.
    authority = parts.netloc.rsplit("@", 1)[-1]
    if authority.startswith("["):
        closing_bracket = authority.find("]")
        if closing_bracket == -1 or "]" in authority[closing_bracket + 1 :]:
            raise ValueError(message)
        try:
            ipaddress.IPv6Address(authority[1:closing_bracket])
        except ValueError as error:
            raise ValueError(message) from error
        suffix = authority[closing_bracket + 1 :]
        if suffix and (
            not suffix.startswith(":") or not suffix[1:].isascii() or not suffix[1:].isdigit()
        ):
            raise ValueError(message)
    elif "[" in authority or "]" in authority or authority.count(":") > 1:
        raise ValueError(message)

    try:
        hostname_ascii = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError(message) from error
    try:
        ipaddress.ip_address(hostname_ascii)
        valid_hostname = True
    except ValueError:
        labels = hostname_ascii.rstrip(".").split(".")
        valid_hostname = (
            bool(hostname_ascii)
            and len(hostname_ascii) <= 253
            and all(_HOST_LABEL_RE.fullmatch(label) for label in labels)
        )

    if not valid_hostname:
        raise ValueError(message)
    if parts.scheme.lower() == "http":
        loopback_host = hostname_ascii.lower() == "localhost" or hostname_ascii in {
            "127.0.0.1",
            "::1",
        }
        if not loopback_host:
            raise ValueError(message)

    return urlunsplit((parts.scheme.lower(), parts.netloc, "", "", ""))


async def _proxy_ingest_chunks(request: Request) -> Response:
    """Forward the ingest callback to the real backend and relay its response."""
    upstream_url = f"{request.app.state.router_upstream_base_url}{INGEST_CALLBACK_PATH}"
    body = await request.body()
    headers = {
        key: value for key, value in request.headers.items() if key.lower() in _FORWARDED_HEADERS
    }
    try:
        async with httpx.AsyncClient(timeout=_INGEST_UPSTREAM_TIMEOUT) as client:
            upstream = await client.post(upstream_url, content=body, headers=headers)
    except httpx.HTTPError as e:
        logger.error(
            "[Router] Ingest callback failed to reach backend",
            upstream=upstream_url,
            error=str(e),
        )
        return Response(
            content=b'{"detail":"ingest router upstream unreachable"}',
            status_code=502,
            media_type="application/json",
        )
    logger.info(
        "[Router] Forwarded ingest callback",
        upstream=upstream_url,
        upstream_status=upstream.status_code,
        bytes=len(body),
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


async def _proxy_llm_request(request: Request) -> Response:
    """Proxy one allowlisted OpenAI-compatible request to the main backend.

    The response is streamed so chat-completion SSE responses retain their
    streaming behaviour. Authentication is still verified by the real backend.
    """
    upstream_path = _LLM_PROXY_UPSTREAM_PATHS.get(request.url.path)
    if upstream_path is None:  # Defensive guard if a route is changed.
        return Response(status_code=404)

    upstream_url = f"{request.app.state.router_upstream_base_url}{upstream_path}"
    body = await request.body()
    headers = {
        key: value for key, value in request.headers.items() if key.lower() in _FORWARDED_HEADERS
    }
    client = httpx.AsyncClient(timeout=_LLM_UPSTREAM_TIMEOUT)
    try:
        upstream = await client.send(
            client.build_request(
                request.method,
                upstream_url,
                content=body,
                headers=headers,
                params=request.query_params,
            ),
            stream=True,
        )
    except httpx.HTTPError as e:
        await client.aclose()
        logger.error(
            "[Router] LLM proxy failed to reach backend", upstream=upstream_url, error=str(e)
        )
        return Response(
            content=b'{"error":{"message":"LLM proxy upstream unreachable","type":"api_error"}}',
            status_code=502,
            media_type="application/json",
        )

    async def stream_body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "cache-control", "x-accel-buffering"}
    }
    logger.info(
        "[Router] Forwarding LLM proxy request", upstream=upstream_url, method=request.method
    )
    return StreamingResponse(
        stream_body(), status_code=upstream.status_code, headers=response_headers
    )


async def _health() -> dict[str, str]:
    return {"status": "ok"}


def create_router_app() -> FastAPI:
    """Build the allowlisted Langflow proxy app and a health probe.

    No other paths are registered, so MCP and every non-allowlisted path return
    404 on this port.
    """
    upstream_base_url = _validate_upstream_base_url(OPENRAG_BACKEND_ROUTER_UPSTREAM_URL)
    app = FastAPI(
        title="OpenRAG Ingest Router",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.router_upstream_base_url = upstream_base_url
    # Reuse the backend's structured access logging so every forwarded callback
    # emits an "[API] Request" line (method/path/status/duration) to the same
    # stdout as the backend. Without this, uvicorn.access is globally silenced.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_api_route(INGEST_CALLBACK_PATH, _proxy_ingest_chunks, methods=["POST"])
    app.add_api_route("/models", _proxy_llm_request, methods=["GET"])
    app.add_api_route("/chat/completions", _proxy_llm_request, methods=["POST"])
    app.add_api_route("/embeddings", _proxy_llm_request, methods=["POST"])
    app.add_api_route("/health", _health, methods=["GET"])
    return app


class _RouterServer(uvicorn.Server):
    """uvicorn Server tailored for the router's daemon thread.

    - Signal handlers are only installable on the main thread, so make them a
      no-op (the router runs on a daemon thread).
    - Emit an explicit readiness/failure log once ``startup()`` has bound (or
      failed to bind) the listening socket, so operators can confirm the router
      is actually up — uvicorn's own "Uvicorn running on …" line is INFO and is
      filtered out by the ``uvicorn.error`` WARNING level.
    """

    def install_signal_handlers(self) -> None:  # pragma: no cover - thread glue
        pass

    async def startup(self, sockets=None) -> None:
        """Log bind failures or readiness after the router server starts."""
        # uvicorn aborts a failed bind (e.g. port in use) by raising SystemExit
        # from startup(); surface it with router context so the failure is
        # attributable, then let the daemon thread unwind.
        try:
            await super().startup(sockets=sockets)
        except (SystemExit, OSError) as e:
            logger.error(
                "[Router] Ingest router failed to start",
                host=OPENRAG_BACKEND_ROUTER_HOST,
                port=OPENRAG_BACKEND_ROUTER_PORT,
                error=str(e),
            )
            raise
        if self.should_exit:
            logger.error(
                "[Router] Ingest router failed to start",
                host=OPENRAG_BACKEND_ROUTER_HOST,
                port=OPENRAG_BACKEND_ROUTER_PORT,
            )
        else:
            logger.info(
                "[Router] Ingest router ready",
                host=OPENRAG_BACKEND_ROUTER_HOST,
                port=OPENRAG_BACKEND_ROUTER_PORT,
                upstream=(
                    f"{self.config.app.state.router_upstream_base_url}{INGEST_CALLBACK_PATH}"
                ),
            )


def start_backend_router() -> None:
    """Launch the proxy app on a daemon thread (it dies with the process)."""
    config = uvicorn.Config(
        create_router_app(),
        host=OPENRAG_BACKEND_ROUTER_HOST,
        port=OPENRAG_BACKEND_ROUTER_PORT,
        log_config=None,
        access_log=ACCESS_LOG_ENABLED,
    )
    threading.Thread(
        target=_RouterServer(config).run,
        daemon=True,
        name="backend-router",
    ).start()
