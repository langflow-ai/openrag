"""Workspace-wide custom metadata field catalog."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MetadataField(SQLModel, table=True):
    __tablename__ = "metadata_fields"

    key: str = Field(primary_key=True, max_length=64)
    metadata_type: str = Field(max_length=16, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
