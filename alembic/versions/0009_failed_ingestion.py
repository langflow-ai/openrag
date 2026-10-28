"""Registry of connector files that failed to ingest.

Revision ID: 0009_failed_ingestion
Revises: 0008_session_conversation_id
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_failed_ingestion"
down_revision = "0008_session_conversation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "failed_ingestion",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("connector_type", sa.String(64), nullable=False),
        sa.Column("file_id", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("content_etag", sa.String(256), nullable=True),
        sa.Column("modified_time", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "connector_type",
            "file_id",
            name="uq_failed_ingestion_user_connector_file",
        ),
    )
    op.create_index("ix_failed_ingestion_user_id", "failed_ingestion", ["user_id"])
    op.create_index("ix_failed_ingestion_connector_type", "failed_ingestion", ["connector_type"])


def downgrade() -> None:
    op.drop_index("ix_failed_ingestion_connector_type", table_name="failed_ingestion")
    op.drop_index("ix_failed_ingestion_user_id", table_name="failed_ingestion")
    op.drop_table("failed_ingestion")
