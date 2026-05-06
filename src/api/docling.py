"""Docling service proxy endpoints."""

import os
import socket
import struct
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from config.settings import DOCLING_SERVE_URL, DOCLING_HOST_IP
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Use values resolved from config boundary
DOCLING_SERVICE_URL = DOCLING_SERVE_URL
HOST_IP = DOCLING_HOST_IP


async def health(request: Request) -> JSONResponse:
    """
    Proxy health check to docling-serve.
    This allows the frontend to check docling status via same-origin request.
    """
    health_url = f"{DOCLING_SERVICE_URL}/health"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                health_url,
                timeout=2.0
            )

            if response.status_code == 200:
                return JSONResponse({
                    "status": "healthy",
                    "host": HOST_IP
                })
            else:
                logger.warning("Docling health check failed", url=health_url, status_code=response.status_code)
                return JSONResponse({
                    "status": "unhealthy",
                    "message": f"Health check failed with status: {response.status_code}",
                    "host": HOST_IP
                }, status_code=503)

    except httpx.TimeoutException:
        logger.warning("Docling health check timeout", url=health_url)
        return JSONResponse({
            "status": "unhealthy",
            "message": "Connection timeout",
            "host": HOST_IP
        }, status_code=503)
    except Exception as e:
        logger.error("Docling health check failed", url=health_url, error=str(e))
        return JSONResponse({
            "status": "unhealthy",
            "message": str(e),
            "host": HOST_IP
        }, status_code=503)
