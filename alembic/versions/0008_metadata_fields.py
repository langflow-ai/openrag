"""custom metadata field catalog

Revision ID: 0008_metadata_fields
Revises: 0007_add_knowledge_delete_anonymous
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_metadata_fields"
down_revision: str | Sequence[str] | None = "0007_add_knowledge_delete_anonymous"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metadata_fields",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("metadata_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_metadata_fields"),
    )
    op.create_index(
        "ix_metadata_fields_metadata_type",
        "metadata_fields",
        ["metadata_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_metadata_fields_metadata_type", table_name="metadata_fields")
    op.drop_table("metadata_fields")
