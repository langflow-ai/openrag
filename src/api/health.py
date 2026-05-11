"""Liveness and readiness probes."""

import asyncio

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from config.settings import clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def health_check(request: Request):
    """Simple liveness probe: Indicates that the OpenRAG Backend service is online and running."""
    return JSONResponse({"status": "ok"}, status_code=200)


async def opensearch_health_ready(request):
    """Readiness probe: verifies OpenSearch dependency is reachable."""
    from config.settings import IBM_AUTH_ENABLED, OPENSEARCH_URL

    if IBM_AUTH_ENABLED:
        logger.debug("[OPENSEARCH] OpenSearch auth mode enabled, health check per-request")
        # In IBM auth mode we cannot rely on the global OpenSearch client
        # (auth is established per-request), so perform a lightweight,
        # unauthenticated connectivity check against the OpenSearch endpoint.
        opensearch_url = OPENSEARCH_URL.rstrip("/")
        try:
            timeout = httpx.Timeout(5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{opensearch_url}/")
            if resp.status_code < 500:
                logger.debug("[OPENSEARCH] OpenSearch health check successful")
                return JSONResponse(
                    {
                        "status": "ready",
                        "dependencies": {"opensearch": "up"},
                        "note": "OpenSearch auth mode - connectivity verified via unauthenticated probe",
                    },
                    status_code=200,
                )
            else:
                logger.debug("[OPENSEARCH] OpenSearch health check failed")
                return JSONResponse(
                    {
                        "status": "not_ready",
                        "dependencies": {"opensearch": "down"},
                        "error": f"Unexpected status from OpenSearch: {resp.status_code}",
                    },
                    status_code=503,
                )
        except Exception as e:
            logger.error("[OPENSEARCH] OpenSearch health check failed", error=str(e))
            return JSONResponse(
                {
                    "status": "not_ready",
                    "dependencies": {"opensearch": "down"},
                    "error": "OpenSearch health check failed",
                },
                status_code=503,
            )

    try:
        await asyncio.wait_for(clients.opensearch.info(), timeout=5.0)
        return JSONResponse(
            {"status": "ready", "dependencies": {"opensearch": "up"}},
            status_code=200,
        )
    except Exception as e:
        logger.error("[OPENSEARCH] OpenSearch health check failed", error=str(e))
        return JSONResponse(
            {
                "status": "not_ready",
                "dependencies": {"opensearch": "down"},
                "error": "OpenSearch health check failed",
            },
            status_code=503,
        )
