from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ComponentState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentBuild(BaseModel):
    git_sha: str | None = None
    build_time: str | None = None
    image: str | None = None
    image_digest: str | None = None


class ComponentStatus(BaseModel):
    name: str
    display_name: str
    status: ComponentState
    required: bool
    latency_ms: int | None = None
    message: str | None = None
    version: str | None = None
    build: ComponentBuild = Field(default_factory=ComponentBuild)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Added by #2178 — None when healthy, last exception detail when not.
    # The frontend uses this as the signal to show the Logs button.
    last_error: str | None = None
    # Added by #2183 — when this component was last checked (ISO-8601 UTC).
    checked_at: str | None = None


class LogEntry(BaseModel):
    timestamp: str  # ISO-8601 UTC
    level: str
    message: str
    detail: str | None = None


class LogsResponse(BaseModel):
    component: str
    entries: list[LogEntry] = Field(default_factory=list)
    count: int


class StatusResponse(BaseModel):
    overall_status: ComponentState
    checked_at: str  # ISO 8601 UTC
    components: list[ComponentStatus] = Field(default_factory=list)


class ComponentActionResponse(BaseModel):
    """Result of a per-component action (sync/restart), carrying fresh status."""

    component: str
    ok: bool
    message: str
    status: ComponentStatus


class DiagnosisResponse(BaseModel):
    """Guidance for the "Debug" button: what's wrong and how to fix it."""

    component: str
    state: ComponentState
    summary: str
    likely_cause: str | None = None
    remediation: list[str] = Field(default_factory=list)
    last_error: str | None = None
    target: str | None = None
