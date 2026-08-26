"""Liveness and readiness probes."""

import asyncio

import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from api.schemas.status import (
    ComponentActionResponse,
    DiagnosisResponse,
    LogsResponse,
    StatusResponse,
)
from api.status_utils import build_logs_response
from config.settings import clients
from dependencies import require_permission
from services.component_logs import KNOWN_COMPONENTS, get_entries
from services.status_diagnostics import diagnose_component
from services.status_service import aggregate_status, check_one
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_console_status(
    user: User = Depends(require_permission("providers:read")),
) -> StatusResponse:
    """Aggregate component readiness for the browser UI. GET /status"""
    try:
        return await aggregate_status()
    except Exception as e:
        logger.error("Failed to get console status", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get status") from e


async def get_console_component_logs(
    component: str,
    tail: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_permission("providers:read")),
) -> LogsResponse:
    """Return recent log entries for one component. GET /status/{component}/logs"""
    return build_logs_response(component, tail)


def _require_known_component(component: str) -> None:
    if component not in KNOWN_COMPONENTS:
        valid = ", ".join(sorted(KNOWN_COMPONENTS))
        raise HTTPException(404, f"Unknown component '{component}'. Valid names: {valid}")


async def sync_console_component(
    component: str,
    user: User = Depends(require_permission("providers:read")),
) -> ComponentActionResponse:
    """Re-run one component's health check. POST /status/{component}/sync"""
    _require_known_component(component)
    status = await check_one(component)
    if status is None:
        raise HTTPException(status_code=503, detail=f"No health check registered for '{component}'")

    return ComponentActionResponse(
        component=component, ok=True, message="Status refreshed.", status=status
    )


async def diagnose_console_component(
    component: str,
    user: User = Depends(require_permission("providers:read")),
) -> DiagnosisResponse:
    """Explain what's wrong with a component and how to fix it.
    GET /status/{component}/diagnose"""
    _require_known_component(component)
    status = await check_one(component)
    if status is None:
        raise HTTPException(status_code=503, detail=f"No health check registered for '{component}'")

    return diagnose_component(status, get_entries(component, tail=50))


async def health_check(request: Request):
    """Simple liveness probe: Indicates that the OpenRAG Backend service is online and running."""
    return JSONResponse({"status": "ok"}, status_code=200)


async def opensearch_health_ready(request: Request):
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
