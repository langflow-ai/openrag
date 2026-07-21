from typing import Annotated

import httpx
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from config.settings import (
    DOCLING_HOST_IP,
    DOCLING_SERVE_URL,
    DOCLING_SERVE_VERIFY_SSL,
)
from dependencies import get_optional_user
from session_manager import User
from utils.logging_config import get_logger
from utils.run_mode_utils import is_run_mode_on_prem, is_run_mode_saas

logger = get_logger(__name__)


# Use values resolved from config boundary
DOCLING_SERVICE_URL = DOCLING_SERVE_URL
HOST_IP = DOCLING_HOST_IP


async def health(
    request: Request, user: Annotated[User | None, Depends(get_optional_user)] = None
) -> JSONResponse:
    """
    Proxy health check to docling-serve.
    This allows the frontend to check docling status via same-origin request.
    """
    health_url = f"{DOCLING_SERVICE_URL}/health"
    headers = {}
    if (is_run_mode_saas() or is_run_mode_on_prem()) and user:
        if user.jwt_token:
            headers["Authorization"] = user.jwt_token

    try:
        async with httpx.AsyncClient(verify=DOCLING_SERVE_VERIFY_SSL) as client:
            response = await client.get(health_url, headers=headers, timeout=2.0)

            if response.status_code == 200:
                return JSONResponse({"status": "healthy", "host": HOST_IP})
            else:
                logger.warning(
                    "Docling health check failed", url=health_url, status_code=response.status_code
                )
                return JSONResponse(
                    {
                        "status": "unhealthy",
                        "message": f"Health check failed with status: {response.status_code}",
                        "host": HOST_IP,
                    },
                    status_code=503,
                )

    except httpx.TimeoutException:
        logger.warning("Docling health check timeout", url=health_url)
        return JSONResponse(
            {"status": "unhealthy", "message": "Connection timeout", "host": HOST_IP},
            status_code=503,
        )
    except Exception as e:
        logger.error("Docling health check failed", url=health_url, error=str(e))
        return JSONResponse(
            {
                "status": "unhealthy",
                "message": "Internal error while checking service health",
                "host": HOST_IP,
            },
            status_code=503,
        )
