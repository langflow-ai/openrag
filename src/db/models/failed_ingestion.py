"""Registry of connector files that failed to ingest.

One row per (user, connector type, source file id). Bucket ingestion consults
it so files that keep failing (corrupt or unsupported documents) are not
re-downloaded and re-attempted on every run. A row stops blocking the file
when the file changes at the source (the stored etag / modified time no longer
match) or when the user retries it from the UI.

``user_id`` is intentionally NOT a foreign key, matching ``session_ownership``:
the registry is bookkeeping and must never make a user deletion or a backfill
gap fail.
"""

from datetime import UTC, datetime

from sqlalchemy import Text, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


class FailedIngestion(SQLModel, table=True):
    __tablename__ = "failed_ingestion"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "connector_type", "file_id", name="uq_failed_ingestion_user_connector_file"
        ),
    )

    id: str = Field(primary_key=True, max_length=32)
    user_id: str = Field(max_length=64, index=True)
    connector_type: str = Field(max_length=64, index=True)
    # Connector file id, e.g. "<bucket>::<key>" for bucket connectors.
    file_id: str = Field(max_length=1024)
    filename: str | None = Field(default=None, max_length=512)
    # Source version the failure was recorded against. Either may be null when
    # the failure happened before the file was downloaded.
    content_etag: str | None = Field(default=None, max_length=256)
    modified_time: str | None = Field(default=None, max_length=64)
    last_error: str | None = Field(
        default=None, sa_column=Column("last_error", Text, nullable=True)
    )
    attempt_count: int = Field(default=1)
    first_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
