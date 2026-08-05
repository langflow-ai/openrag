"""In-memory ring buffer for per-component log entries.

Intentionally free of FastAPI imports so services can use it at any layer.
Thread-safe via a per-component threading.Lock.
"""

import re
import threading
from collections import deque
from datetime import UTC, datetime
from typing import TypedDict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUFFER_MAXLEN = 200

# Valid component names — used by the API layer for 404 gating.
KNOWN_COMPONENTS: frozenset[str] = frozenset({"openrag", "langflow", "docling", "opensearch"})

# Reuse the same pattern as logging_config._SENSITIVE_HEADER_RE so that keys
# / tokens never surface in HTTP responses.
_SENSITIVE_RE = re.compile(r"(key|token|secret|password|apikey|credential|jwt|auth)", re.IGNORECASE)
# Strip bare Bearer tokens from free-form detail strings.
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class LogEntry(TypedDict):
    timestamp: str  # ISO-8601 UTC
    level: str  # "debug" | "info" | "warning" | "error" | "critical"
    message: str
    detail: str | None


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

# deque per component name
_buffers: dict[str, deque[LogEntry]] = {}
_locks: dict[str, threading.Lock] = {}
# last outcome per component: True = last check was healthy, False = unhealthy/unknown
_last_ok: dict[str, bool] = {}
_state_lock = threading.Lock()


def _get_or_create(component: str) -> tuple[deque[LogEntry], threading.Lock]:
    """Return (buffer, lock) for *component*, creating them on first access."""
    with _state_lock:
        if component not in _buffers:
            _buffers[component] = deque(maxlen=BUFFER_MAXLEN)
            _locks[component] = threading.Lock()
        return _buffers[component], _locks[component]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def _redact(text: str | None) -> str | None:
    """Strip Bearer tokens from *text*. Key/secret values are not present in
    free-form detail strings (they come from exception messages), but Bearer
    tokens can appear in httpx error repr if auth headers are dumped."""
    if text is None:
        return None
    return _BEARER_RE.sub("Bearer ***", text)


def _redact_dict(event_dict: dict) -> dict:
    """Return a shallow copy of *event_dict* with sensitive values masked."""
    out = {}
    for k, v in event_dict.items():
        if _SENSITIVE_RE.search(str(k)):
            out[k] = "***"
        elif isinstance(v, str):
            out[k] = _BEARER_RE.sub("Bearer ***", v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record(component: str, level: str, message: str, detail: str | None = None) -> None:
    """Append one entry to *component*'s ring buffer.

    Unknown component names are silently accepted so callers never need to
    guard — the buffer just grows dynamically (still capped at BUFFER_MAXLEN).
    """
    buf, lock = _get_or_create(component)
    entry: LogEntry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
        "detail": _redact(detail),
    }
    with lock:
        buf.append(entry)


def record_check_result(
    component: str,
    ok: bool,
    message: str,
    detail: str | None = None,
) -> None:
    """Write to the buffer with flood-prevention logic.

    - Failure (ok=False): always records an error entry.
    - Recovery (False→True transition): records one info "recovered" entry.
    - Steady healthy (True→True): records nothing, keeping error history intact.
    """
    with _state_lock:
        was_ok = _last_ok.get(component, True)  # assume healthy on first call
        _last_ok[component] = ok

    if not ok:
        record(component, "error", message, detail=detail)
    elif not was_ok:
        # Transition: unhealthy → healthy
        record(component, "info", f"recovered: {message}")


def get_entries(component: str, tail: int = 100) -> list[LogEntry]:
    """Return up to *tail* most-recent entries for *component* (oldest→newest).

    Returns an empty list for unknown / never-recorded components.
    """
    if component not in _buffers:
        return []
    buf, lock = _get_or_create(component)
    with lock:
        entries = list(buf)
    if tail >= len(entries):
        return entries
    return entries[-tail:]
