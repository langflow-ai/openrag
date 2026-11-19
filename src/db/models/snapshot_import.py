"""Registry tables for the OpenSearch snapshot import connector.

``snapshot_sources`` holds S3 locations of OpenSearch snapshot repositories
(own encrypted store, not ConnectionManager connections). ``snapshot_imports``
is one restore of a chosen snapshot under an opaque slug; ``snapshot_datasets``
is one restored index ("dataset") of an import. Datasets keep a stable id across
re-imports; only ``concrete_index`` changes with the generation.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class SnapshotSource(SQLModel, table=True):
    __tablename__ = "snapshot_sources"

    id: str = Field(primary_key=True, max_length=64)
    owner_user_id: str = Field(max_length=255, index=True)
    name: str = Field(max_length=256)
    endpoint_url: str | None = Field(default=None, max_length=1024)
    region: str = Field(default="us-east-1", max_length=64)
    bucket: str = Field(max_length=255)
    prefix: str = Field(default="", max_length=1024)
    path_style: bool = Field(default=True)
    verify_tls: bool = Field(default=True)
    # JSON envelopes produced by utils.encryption.encrypt_secret.
    access_key_enc: str | None = Field(default=None, sa_column=Column("access_key_enc", Text))
    secret_key_enc: str | None = Field(default=None, sa_column=Column("secret_key_enc", Text))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SnapshotImport(SQLModel, table=True):
    __tablename__ = "snapshot_imports"

    id: str = Field(primary_key=True, max_length=64)
    slug: str = Field(max_length=16, unique=True, index=True)
    name: str = Field(max_length=256)
    source_id: str = Field(foreign_key="snapshot_sources.id", max_length=64)
    owner_user_id: str = Field(max_length=255, index=True)
    os_principal: str | None = Field(default=None, max_length=512)
    shared: bool = Field(default=False)
    snapshot_name: str = Field(max_length=512)
    snapshot_uuid: str = Field(default="", max_length=128)
    written_by_version: str | None = Field(default=None, max_length=64)
    source_indices: list[str] = Field(
        default_factory=list, sa_column=Column("source_indices", JSON, nullable=False)
    )
    staged_bytes: int = Field(
        default=0, sa_column=Column("staged_bytes", BigInteger, nullable=False, default=0)
    )
    # staging | restoring | review | active | failed | deleting
    status: str = Field(default="staging", max_length=16)
    generation: int = Field(default=1)
    # Highest generation a job ever reserved. A retry builds ``max(generation, attempt_generation) + 1``
    # so it can never reuse a generation that an interrupted attempt left subject to cleanup.
    attempt_generation: int = Field(default=0)
    # idle | queued | running | failed | cancelled | recovery
    # ``recovery``: the last job may have left aliases/indices behind that must be reconciled
    # before the import accepts another job (re-import) or visibility-changing mutation.
    job_state: str = Field(default="idle", max_length=16)
    # import | reimport | delete
    job_kind: str = Field(default="import", max_length=16)
    job_error: str | None = Field(default=None, sa_column=Column("job_error", Text))
    task_id: str | None = Field(default=None, max_length=64)
    # {"generation": N, "swaps": [[alias, new_index, old_index|null], ...]}: written before an
    # alias publication is attempted, cleared once the DB references the new generation (or the
    # old targets are restored). Lets failure handling and restart recovery inspect real aliases.
    pending_publication: dict[str, Any] | None = Field(
        default=None, sa_column=Column("pending_publication", JSON, nullable=True)
    )
    # {index: {inline_setting: [lines]}}
    analyser_inlines: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("analyser_inlines", JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SnapshotDataset(SQLModel, table=True):
    __tablename__ = "snapshot_datasets"
    __table_args__ = (
        UniqueConstraint("import_id", "ordinal", name="uq_snapshot_datasets_import_ordinal"),
    )

    id: str = Field(primary_key=True, max_length=64)
    import_id: str = Field(foreign_key="snapshot_imports.id", max_length=64, index=True)
    ordinal: int
    source_index: str = Field(max_length=255)
    index_alias: str = Field(max_length=255)
    concrete_index: str = Field(max_length=255)
    display_name: str = Field(max_length=256)
    description: str = Field(default="", sa_column=Column("description", Text, nullable=False))
    field_map: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("field_map", JSON, nullable=False)
    )
    retrieval: dict[str, Any] = Field(
        default_factory=lambda: {"mode": "lexical"},
        sa_column=Column("retrieval", JSON, nullable=False),
    )
    doc_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
