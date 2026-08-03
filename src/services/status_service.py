import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from api.schemas.status import ComponentState, ComponentStatus, StatusResponse
from services.component_logs import record
from services.status_checks import (
    check_docling,
    check_langflow,
    check_openrag_backend,
    check_opensearch,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

CHECK_TIMEOUT_S = 5.0

CHECK_SPECS = [check_openrag_backend, check_docling, check_langflow, check_opensearch]


async def _run_check(fn: Callable[[], Awaitable[ComponentStatus]]) -> ComponentStatus:
    """Run one check function, wrapping timeouts and unexpected exceptions.

    Both failure modes are recorded to the component log buffer so that the
    /v1/status/{component}/logs endpoint can surface the detail later.
    """
    name = fn.__name__.replace("check_", "")
    try:
        return await asyncio.wait_for(fn(), timeout=CHECK_TIMEOUT_S)
    except TimeoutError:
        msg = f"Status check timed out after {CHECK_TIMEOUT_S}s"
        logger.warning("Status check timed out", component=name, timeout_s=CHECK_TIMEOUT_S)
        record(name, "error", msg, detail=f"asyncio.TimeoutError — timeout={CHECK_TIMEOUT_S}s")
        return ComponentStatus(
            name=name,
            display_name=name.title(),
            status=ComponentState.UNKNOWN,
            required=True,
            message="Status check did not complete",
            last_error=msg,
        )
    except Exception as e:
        msg = "Status check did not complete"
        logger.warning("Status check did not complete", component=name, error=str(e))
        record(name, "error", msg, detail=f"{type(e).__name__}: {e}")
        return ComponentStatus(
            name=name,
            display_name=name.title(),
            status=ComponentState.UNKNOWN,
            required=True,
            message=msg,
            last_error=f"{type(e).__name__}: {e}",
        )


def _worst_status(results: list[ComponentStatus]) -> ComponentState:
    """This calculates the final status (the worst one)"""
    severity = {
        ComponentState.HEALTHY: 0,
        ComponentState.DEGRADED: 1,
        ComponentState.UNKNOWN: 2,
        ComponentState.UNHEALTHY: 2,
    }

    severity_in_order = [ComponentState.HEALTHY, ComponentState.DEGRADED, ComponentState.UNHEALTHY]

    return severity_in_order[max((severity[r.status] for r in results), default=0)]


async def aggregate_status() -> StatusResponse:
    """TODO: add docstrings here"""
    results = await asyncio.gather(*(_run_check(fn) for fn in CHECK_SPECS))

    return StatusResponse(
        overall_status=_worst_status(list(results)),
        checked_at=datetime.now(UTC).isoformat(),
        components=list(results),
    )
