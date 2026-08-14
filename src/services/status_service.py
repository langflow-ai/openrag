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


def _check_name(fn: Callable) -> str:
    return fn.__name__.replace("check_", "").replace("openrag_backend", "openrag")


# component name → its check function, for refreshing a single component (#2183).
CHECK_BY_NAME: dict[str, Callable[[], Awaitable[ComponentStatus]]] = {
    _check_name(fn): fn for fn in CHECK_SPECS
}


async def _run_check(fn: Callable[[], Awaitable[ComponentStatus]]) -> ComponentStatus:
    """Run one check function, wrapping timeouts and unexpected exceptions.

    Both failure modes are recorded to the component log buffer so that the
    /v1/status/{component}/logs endpoint can surface the detail later.
    """
    name = _check_name(fn)
    try:
        result = await asyncio.wait_for(fn(), timeout=CHECK_TIMEOUT_S)
    except TimeoutError:
        msg = f"Status check timed out after {CHECK_TIMEOUT_S}s"
        logger.warning("Status check timed out", component=name, timeout_s=CHECK_TIMEOUT_S)
        record(name, "error", msg, detail=f"asyncio.TimeoutError — timeout={CHECK_TIMEOUT_S}s")
        result = ComponentStatus(
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
        result = ComponentStatus(
            name=name,
            display_name=name.title(),
            status=ComponentState.UNKNOWN,
            required=True,
            message=msg,
            last_error=f"{type(e).__name__}: {e}",
        )

    # Stamp the check time here so every code path (aggregate or single) is consistent.
    result.checked_at = datetime.now(UTC).isoformat()
    return result


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


async def check_one(name: str) -> ComponentStatus | None:
    """Re-run one component's health check (#2183 "Sync"). None if unknown."""
    fn = CHECK_BY_NAME.get(name)
    return await _run_check(fn) if fn is not None else None
