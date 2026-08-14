"""Rule-based diagnosis for the Console Status "Debug" button (#2183).

Turns a component's status + recent log detail into plain-English guidance:
what's likely wrong and concrete steps to fix it.
"""

from api.schemas.status import ComponentState, ComponentStatus, DiagnosisResponse
from services.component_logs import LogEntry

_DISPLAY = {
    "openrag": "OpenRAG Backend",
    "langflow": "Langflow",
    "docling": "Docling",
    "opensearch": "OpenSearch",
}

_CONNECTION_HINTS = ("connect", "refused", "timed out", "timeout", "unreachable")


def _target(component: str) -> str | None:
    from config.settings import DOCLING_SERVE_URL, LANGFLOW_URL, OPENSEARCH_URL

    return {
        "langflow": f"{LANGFLOW_URL}/api/v1/version",
        "docling": f"{DOCLING_SERVE_URL}/version",
        "opensearch": OPENSEARCH_URL,
    }.get(component)


def diagnose_component(
    status: ComponentStatus, entries: list[LogEntry] | None = None
) -> DiagnosisResponse:
    component = status.name
    display = _DISPLAY.get(component, status.display_name or component)
    target = _target(component)
    last_err = next(
        (e.get("detail") for e in reversed(entries or []) if e.get("level") in ("error", "critical")),
        None,
    )
    detail = status.last_error or last_err

    def resp(summary, cause=None, steps=None):
        return DiagnosisResponse(
            component=component,
            state=status.status,
            summary=summary,
            likely_cause=cause,
            remediation=steps or [],
            last_error=detail,
            target=target,
        )

    if status.status == ComponentState.HEALTHY:
        return resp(f"{display} is healthy — no action needed.")

    if component == "opensearch" and status.status == ComponentState.DEGRADED:
        return resp(
            f"{display} cluster health is yellow (degraded).",
            "Replica shards are unassigned — normal for a single-node dev cluster.",
            [
                "On a single-node setup this is expected and safe to ignore.",
                "For production, add data nodes so replicas can be assigned.",
            ],
        )

    if detail and any(h in detail.lower() for h in _CONNECTION_HINTS):
        return resp(
            f"{display} is unreachable — the backend couldn't connect to it.",
            f"The service isn't accepting connections at {target}. It may be stopped or still starting.",
            [
                f"Confirm the service is running at {target}.",
                'Click "Sync" once it\'s back to re-check.',
                'Check "Logs" for the underlying error.',
            ],
        )

    if status.status == ComponentState.UNKNOWN:
        return resp(
            f"{display}'s status could not be determined.",
            "The health check didn't complete — the client may not be initialized, or it timed out.",
            [
                'Click "Sync" to re-run the check.',
                "Wait a moment if the backend is still starting.",
            ],
        )

    return resp(
        f"{display} reported: {status.message or status.status}.",
        detail or "The service responded but not in a healthy state.",
        ['Click "Sync" to confirm the current status.', 'Review "Logs" for details.'],
    )
