"""Standalone ingestion-callback proxy router.

A deliberately tiny FastAPI/uvicorn app that exposes ONLY the Langflow ingest
callback endpoint (``POST /internal/ingest/chunks``) and forwards it to the real
backend. It runs in the same process as the main backend (a daemon thread on its
own port) when ``OPENRAG_BACKEND_ROUTER_ENABLE`` is set, so Langflow's reachable
surface narrows to this single route instead of the full backend internal API.

It is a thin reverse proxy only — it does NOT validate the ingest JWT; the real
backend still does. Its sole job is network-surface isolation.
"""

from __future__ import annotations

import threading

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

from app.middleware import RequestLoggingMiddleware
from config.settings import (
    ACCESS_LOG_ENABLED,
    INGEST_CALLBACK_PATH,
    OPENRAG_BACKEND_ROUTER_HOST,
    OPENRAG_BACKEND_ROUTER_PORT,
    OPENRAG_BACKEND_ROUTER_UPSTREAM_URL,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Where the proxy forwards callbacks: loopback to the co-located backend (NOT the
# advertised service name, which may not resolve from where the router runs).
_UPSTREAM_URL = f"{OPENRAG_BACKEND_ROUTER_UPSTREAM_URL}{INGEST_CALLBACK_PATH}"

# Only these request headers are forwarded upstream; everything else (Host,
# hop-by-hop headers, etc.) is dropped so the router cannot be abused as an open
# proxy. The ingest token travels in either Authorization or the custom header.
_FORWARDED_HEADERS = ("authorization", "x-openrag-ingest-token", "content-type")
_UPSTREAM_TIMEOUT = httpx.Timeout(60.0)


async def _proxy_ingest_chunks(request: Request) -> Response:
    """Forward the ingest callback to the real backend and relay its response."""
    upstream_url = _UPSTREAM_URL
    body = await request.body()
    headers = {
        key: value for key, value in request.headers.items() if key.lower() in _FORWARDED_HEADERS
    }
    try:
        async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as client:
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


async def _health() -> dict[str, str]:
    return {"status": "ok"}


def create_router_app() -> FastAPI:
    """Build the minimal proxy app: only the ingest callback + a health probe.

    No other paths are registered, so every other request returns 404.
    """
    app = FastAPI(
        title="OpenRAG Ingest Router",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Reuse the backend's structured access logging so every forwarded callback
    # emits an "[API] Request" line (method/path/status/duration) to the same
    # stdout as the backend. Without this, uvicorn.access is globally silenced.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_api_route(INGEST_CALLBACK_PATH, _proxy_ingest_chunks, methods=["POST"])
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
                upstream=_UPSTREAM_URL,
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
