"""Docling service proxy endpoints."""

import socket
import struct
from pathlib import Path

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.container_utils import (
    detect_container_environment,
    get_container_host,
    guess_host_ip_for_containers,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_gateway_ip_from_route() -> str | None:
    """Return the default gateway IP visible from the current network namespace."""
    try:
        with Path("/proc/net/route").open() as route_table:
            next(route_table)  # Skip header
            for line in route_table:
                fields = line.strip().split()
                min_fields = 3  # interface, destination, gateway
                if len(fields) >= min_fields and fields[1] == "00000000":
                    gateway_hex = fields[2]
                    gw_int = int(gateway_hex, 16)
                    gateway_ip = socket.inet_ntoa(struct.pack("<L", gw_int))
                    return gateway_ip
    except (FileNotFoundError, PermissionError, IndexError, ValueError) as err:
        logger.warning("Could not read routing table: %s", err)

    return None


def determine_docling_host() -> str:
    """Determine the host address used for docling health checks."""
    container_type = detect_container_environment()
    if container_type:
        container_host = get_container_host()
        if container_host:
            logger.info("Using container-aware host '%s'", container_host)
            return container_host

        gateway_ip = _get_gateway_ip_from_route()
        if gateway_ip:
            logger.info("Detected host gateway IP: %s", gateway_ip)
            return gateway_ip

    # Either we're not inside a container or gateway detection failed.
    fallback_ip = guess_host_ip_for_containers(logger=logger)
    if container_type:
        logger.info("Falling back to container bridge host %s", fallback_ip)
    else:
        logger.info("Running outside a container; using host %s", fallback_ip)
    return fallback_ip


# Detect the host IP once at startup
HOST_IP = determine_docling_host()
DOCLING_SERVICE_URL = f"http://{HOST_IP}:5001"


async def health(request: Request) -> JSONResponse:
    """
    Proxy health check to docling-serve.
    This allows the frontend to check docling status via same-origin request.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DOCLING_SERVICE_URL}/health",
                timeout=2.0
            )

            if response.status_code == 200:
                return JSONResponse({
                    "status": "healthy",
                    "host": HOST_IP
                })
            else:
                return JSONResponse({
                    "status": "unhealthy",
                    "message": f"Health check failed with status: {response.status_code}",
                    "host": HOST_IP
                }, status_code=503)

    except httpx.TimeoutException:
        return JSONResponse({
            "status": "unhealthy",
            "message": "Connection timeout",
            "host": HOST_IP
        }, status_code=503)
    except Exception as e:
        logger.error("Docling health check failed", error=str(e))
        return JSONResponse({
            "status": "unhealthy",
            "message": str(e),
            "host": HOST_IP
        }, status_code=503)
