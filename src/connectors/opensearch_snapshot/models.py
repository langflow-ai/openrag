"""Request and response models for the OpenSearch snapshot import API.

Response models never carry credentials: sources expose ``has_credentials``
only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── requests ─────────────────────────────────────────────────────────────


def _strip_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Name is required")
    return value


class SourceCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    endpoint_url: str | None = Field(default=None, max_length=1024)
    region: str = Field(default="us-east-1", min_length=1, max_length=64)
    bucket: str = Field(min_length=1, max_length=255)
    prefix: str = Field(default="", max_length=1024)
    access_key: str | None = Field(default=None, max_length=512)
    secret_key: str | None = Field(default=None, max_length=2048)
    path_style: bool = True
    verify_tls: bool = True

    _clean_name = field_validator("name")(_strip_name)


class SourcePatchBody(BaseModel):
    """Same fields as create, all optional; omitted keys keep their stored value."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    endpoint_url: str | None = Field(default=None, max_length=1024)
    region: str | None = Field(default=None, min_length=1, max_length=64)
    bucket: str | None = Field(default=None, min_length=1, max_length=255)
    prefix: str | None = Field(default=None, max_length=1024)
    access_key: str | None = Field(default=None, max_length=512)
    secret_key: str | None = Field(default=None, max_length=2048)
    path_style: bool | None = None
    verify_tls: bool | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else _strip_name(value)


class PreflightBody(BaseModel):
    snapshot: str = Field(min_length=1, max_length=512)
    indices: list[str] = Field(min_length=1, max_length=100)


class AnalyserFileBody(BaseModel):
    index: str
    setting: str
    content: str


class ImportCreateBody(BaseModel):
    source_id: str
    snapshot: str = Field(min_length=1, max_length=512)
    indices: list[str] = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=256)
    shared: bool = False
    analyser_files: list[AnalyserFileBody] = Field(default_factory=list)

    _clean_name = field_validator("name")(_strip_name)


class DatasetPatchBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    field_map: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None

    @field_validator("display_name")
    @classmethod
    def _clean_display_name(cls, value: str | None) -> str | None:
        return None if value is None else _strip_name(value)


class ShareBody(BaseModel):
    shared: bool


class ReimportPreflightBody(BaseModel):
    snapshot: str = Field(min_length=1, max_length=512)


class ReimportBody(BaseModel):
    snapshot: str = Field(min_length=1, max_length=512)
    analyser_files: list[AnalyserFileBody] = Field(default_factory=list)


# ── responses ────────────────────────────────────────────────────────────


class StatusOut(BaseModel):
    enabled: bool
    reason: str | None = None
    staging_type: str | None = None
    security_managed: bool
    private_supported: bool


class SourceOut(BaseModel):
    id: str
    name: str
    endpoint_url: str | None
    region: str
    bucket: str
    prefix: str
    path_style: bool
    verify_tls: bool
    has_credentials: bool
    created_at: datetime
    updated_at: datetime


class SnapshotIndexOut(BaseModel):
    name: str
    size_bytes: int


class SnapshotOut(BaseModel):
    name: str
    uuid: str
    state: str
    version: str | None
    indices: list[SnapshotIndexOut]


class SnapshotListOut(BaseModel):
    repository_generation: int
    snapshots: list[SnapshotOut]


class IssueOut(BaseModel):
    code: str
    message: str
    index: str | None = None


class AnalyserFileRefOut(BaseModel):
    index: str
    setting: str
    path: str
    inline_setting: str


class PreflightIndexOut(BaseModel):
    name: str
    created_version: str | None = None
    doc_count: int | None = None


class PreflightOut(BaseModel):
    ok: bool
    blockers: list[IssueOut]
    warnings: list[IssueOut]
    analyser_files: list[AnalyserFileRefOut]
    staged_bytes: int
    restored_bytes: int
    indices: list[PreflightIndexOut]


class FieldOut(BaseModel):
    name: str
    type: str
    dims: int | None = None


class VectorFieldOut(FieldOut):
    engine: str | None = None


class DatasetOut(BaseModel):
    id: str
    ordinal: int
    source_index: str
    index_alias: str
    display_name: str
    description: str
    doc_count: int
    field_map: dict[str, Any]
    retrieval: dict[str, Any]
    fields: list[FieldOut]
    vector_fields: list[VectorFieldOut]
    available_models: list[str]


class JobOut(BaseModel):
    state: str
    kind: str
    error: str | None
    task_id: str | None


class ImportOut(BaseModel):
    id: str
    slug: str
    name: str
    source_id: str
    snapshot_name: str
    snapshot_uuid: str
    written_by_version: str | None
    source_indices: list[str]
    staged_bytes: int
    status: str
    generation: int
    shared: bool
    is_owner: bool
    job: JobOut
    role_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    datasets: list[DatasetOut]
