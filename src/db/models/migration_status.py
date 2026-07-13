"""Tracks one-shot runtime migrations (e.g. JSON->DB)."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MigrationStatus(SQLModel, table=True):
    __tablename__ = "migration_status"

    name: str = Field(primary_key=True, max_length=128)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: str = Field(default="", max_length=2048)
