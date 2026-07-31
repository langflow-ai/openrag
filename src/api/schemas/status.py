from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Any


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

class StatusResponse(BaseModel):
    overall_status: ComponentState
    checked_at: str # ISO 8601 UTC
    components: list[ComponentStatus] = Field(default_factory=list)