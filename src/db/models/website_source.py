"""Persistent state for managed website sources and their child pages."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class WebsiteSource(SQLModel, table=True):
    __tablename__ = "website_sources"
    id: str = Field(primary_key=True, max_length=64)
    owner_id: str = Field(max_length=64, index=True)
    name: str = Field(max_length=256)
    starting_url: str = Field(max_length=2048)
    crawl_settings: dict = Field(sa_column=Column(JSON, nullable=False))
    change_detection: str = Field(default="normalized_content_hash", max_length=32)
    resync_behavior: str = Field(default="full", max_length=32)
    removed_page_behavior: str = Field(default="retain", max_length=32)
    status: str = Field(default="processing", max_length=32, index=True)
    last_error: str | None = Field(default=None, max_length=2048)
    last_task_id: str | None = Field(default=None, max_length=64, index=True)
    last_successful_sync_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WebsitePage(SQLModel, table=True):
    __tablename__ = "website_pages"
    __table_args__ = (
        UniqueConstraint("web_source_id", "canonical_url", name="uq_website_page_source_url"),
        Index("ix_website_pages_source_status", "web_source_id", "status"),
    )
    id: str = Field(primary_key=True, max_length=64)
    web_source_id: str = Field(foreign_key="website_sources.id", max_length=64, index=True)
    canonical_url: str = Field(max_length=2048)
    final_url: str | None = Field(default=None, max_length=2048)
    title: str = Field(max_length=512)
    document_id: str = Field(max_length=64, unique=True, index=True)
    content_hash: str | None = Field(default=None, max_length=64)
    depth: int = Field(default=0)
    content_type: str | None = Field(default=None, max_length=128)
    byte_size: int = Field(default=0)
    chunk_count: int = Field(default=0)
    status: str = Field(default="processing", max_length=32, index=True)
    suppressed_by_user: bool = Field(default=False, index=True)
    last_seen_at: datetime | None = Field(default=None)
    last_ingested_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WebsiteCrawlRun(SQLModel, table=True):
    __tablename__ = "website_crawl_runs"
    id: str = Field(primary_key=True, max_length=64)
    web_source_id: str = Field(foreign_key="website_sources.id", max_length=64, index=True)
    task_id: str | None = Field(default=None, max_length=64, index=True)
    settings_snapshot: dict = Field(sa_column=Column(JSON, nullable=False))
    completed: bool = Field(default=False)
    capped: bool = Field(default=False)
    error: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = Field(default=None)
