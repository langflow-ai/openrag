import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from api.schemas.status import ComponentState, ComponentStatus, StatusResponse
from config.settings import is_langflow_disabled
from services.component_logs import record
from services.status_checks import (
    check_docling,
    check_langflow,
    check_openrag_backend,
    check_opensearch,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Total wall-clock deadline per check. It must exceed status_checks._CHECK_TIMEOUT_S, which
# httpx applies per phase, so a slow service is diagnosed by its own check rather than
# cancelled here into UNKNOWN. It is also the only bound on the OpenSearch check, and it
# caps /status latency, since that endpoint waits for its slowest check.
CHECK_TIMEOUT_S = 8.0

CHECK_SPECS: list[Callable[[], Awaitable[ComponentStatus]]] = [
    check_openrag_backend,
    check_docling,
    check_langflow,
    check_opensearch,
]


def _check_specs() -> list[Callable[[], Awaitable[ComponentStatus]]]:
    """Return only components that are part of the active deployment."""

    if is_langflow_disabled():
        return [check for check in CHECK_SPECS if check is not check_langflow]
    return CHECK_SPECS


def _check_name(fn: Callable) -> str:
    return fn.__name__.replace("check_", "").replace("openrag_backend", "openrag")


# component name → its check function, for refreshing a single component (#2183).
def _checks_by_name() -> dict[str, Callable[[], Awaitable[ComponentStatus]]]:
    return {_check_name(fn): fn for fn in _check_specs()}


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


SEVERITY_ORDER = [
    ComponentState.HEALTHY,
    ComponentState.DEGRADED,
    ComponentState.UNKNOWN,
    ComponentState.UNHEALTHY,
]


def _worst_status(results: list[ComponentStatus]) -> ComponentState:
    """This calculates the final status (the worst one)"""
    severity = {state: i for i, state in enumerate(SEVERITY_ORDER)}
    return SEVERITY_ORDER[max((severity[r.status] for r in results), default=0)]


async def aggregate_status() -> StatusResponse:
    """Runs all component health checks concurrently and return the aggregate status"""
    results = await asyncio.gather(*(_run_check(fn) for fn in _check_specs()))

    return StatusResponse(
        overall_status=_worst_status(list(results)),
        checked_at=datetime.now(UTC).isoformat(),
        components=list(results),
    )


async def check_one(name: str) -> ComponentStatus | None:
    """Re-run one component's health check (#2183 "Sync"). None if unknown."""
    fn = _checks_by_name().get(name)
    return await _run_check(fn) if fn is not None else None
