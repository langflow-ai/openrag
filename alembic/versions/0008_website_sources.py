"""add managed URL website source tables

Revision ID: 0008_website_sources
Revises: 0007_add_knowledge_delete_anonymous
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_website_sources"
down_revision: str | Sequence[str] | None = "0007_add_knowledge_delete_anonymous"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("website_sources",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False), sa.Column("starting_url", sa.String(2048), nullable=False),
        sa.Column("crawl_settings", sa.JSON(), nullable=False), sa.Column("resync_behavior", sa.String(32), nullable=False),
        sa.Column("removed_page_behavior", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_error", sa.String(2048)), sa.Column("last_task_id", sa.String(64)),
        sa.Column("last_successful_sync_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_website_sources_owner_id", "website_sources", ["owner_id"])
    op.create_index("ix_website_sources_status", "website_sources", ["status"])
    op.create_index("ix_website_sources_last_task_id", "website_sources", ["last_task_id"])
    op.create_table("website_pages",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("web_source_id", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False), sa.Column("final_url", sa.String(2048)), sa.Column("title", sa.String(512), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False), sa.Column("content_hash", sa.String(64)), sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(128)), sa.Column("byte_size", sa.Integer(), nullable=False), sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("suppressed_by_user", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime()), sa.Column("last_ingested_at", sa.DateTime()), sa.Column("last_error", sa.String(2048)),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["web_source_id"], ["website_sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("web_source_id", "canonical_url", name="uq_website_page_source_url"), sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_website_pages_source_status", "website_pages", ["web_source_id", "status"])
    op.create_index("ix_website_pages_web_source_id", "website_pages", ["web_source_id"])
    op.create_table("website_crawl_runs",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("web_source_id", sa.String(64), nullable=False), sa.Column("task_id", sa.String(64)),
        sa.Column("settings_snapshot", sa.JSON(), nullable=False), sa.Column("completed", sa.Boolean(), nullable=False), sa.Column("capped", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(2048)), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["web_source_id"], ["website_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_website_crawl_runs_web_source_id", "website_crawl_runs", ["web_source_id"])
    op.create_index("ix_website_crawl_runs_task_id", "website_crawl_runs", ["task_id"])


def downgrade() -> None:
    op.drop_table("website_crawl_runs")
    op.drop_table("website_pages")
    op.drop_table("website_sources")
