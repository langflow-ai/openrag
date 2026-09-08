"""Shared helpers for the /status log endpoints.

Both the browser-session handler (api.health) and the public API handler
(api.v1.status) expose GET …/status/{component}/logs.  Their bodies are
identical apart from the auth dependency, so the logic lives here once.
"""

from fastapi import HTTPException

from api.schemas.status import LogEntry, LogsResponse
from services.component_logs import KNOWN_COMPONENTS, get_entries


def build_logs_response(component: str, tail: int) -> LogsResponse:
    """Validate *component*, read its ring buffer, and return a LogsResponse.

    Raises HTTPException 404 for unknown component names.
    The *tail* value is already validated by FastAPI's Query constraint on the
    calling handler (ge=1, le=500) before this function is reached.
    """
    if component not in KNOWN_COMPONENTS:
        valid = ", ".join(sorted(KNOWN_COMPONENTS))
        raise HTTPException(
            status_code=404,
            detail=f"Unknown component '{component}'. Valid names: {valid}",
        )

    raw = get_entries(component, tail=tail)
    entries = [LogEntry(**e) for e in raw]
    return LogsResponse(component=component, entries=entries, count=len(entries))
