"""OpenSearch snapshot import registry: sources, imports, datasets

Revision ID: 0011_snapshot_imports
Revises: 0010_move_legacy_native_chat
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_snapshot_imports"
down_revision = "0010_move_legacy_native_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_sources",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1024), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=1024), nullable=False),
        sa.Column("path_style", sa.Boolean(), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("access_key_enc", sa.Text(), nullable=True),
        sa.Column("secret_key_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_snapshot_sources_owner_user_id", "snapshot_sources", ["owner_user_id"])

    op.create_table(
        "snapshot_imports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("slug", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=255), nullable=False),
        sa.Column("os_principal", sa.String(length=512), nullable=True),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("snapshot_name", sa.String(length=512), nullable=False),
        sa.Column("snapshot_uuid", sa.String(length=128), nullable=False),
        sa.Column("written_by_version", sa.String(length=64), nullable=True),
        sa.Column("source_indices", sa.JSON(), nullable=False),
        sa.Column("staged_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempt_generation", sa.Integer(), nullable=False),
        sa.Column("job_state", sa.String(length=16), nullable=False),
        sa.Column("job_kind", sa.String(length=16), nullable=False),
        sa.Column("job_error", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("pending_publication", sa.JSON(), nullable=True),
        sa.Column("analyser_inlines", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["snapshot_sources.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_snapshot_imports_slug", "snapshot_imports", ["slug"], unique=True)
    op.create_index("ix_snapshot_imports_owner_user_id", "snapshot_imports", ["owner_user_id"])

    op.create_table(
        "snapshot_datasets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("import_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_index", sa.String(length=255), nullable=False),
        sa.Column("index_alias", sa.String(length=255), nullable=False),
        sa.Column("concrete_index", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("field_map", sa.JSON(), nullable=False),
        sa.Column("retrieval", sa.JSON(), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["snapshot_imports.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("import_id", "ordinal", name="uq_snapshot_datasets_import_ordinal"),
    )
    op.create_index("ix_snapshot_datasets_import_id", "snapshot_datasets", ["import_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_datasets_import_id", table_name="snapshot_datasets")
    op.drop_table("snapshot_datasets")
    op.drop_index("ix_snapshot_imports_owner_user_id", table_name="snapshot_imports")
    op.drop_index("ix_snapshot_imports_slug", table_name="snapshot_imports")
    op.drop_table("snapshot_imports")
    op.drop_index("ix_snapshot_sources_owner_user_id", table_name="snapshot_sources")
    op.drop_table("snapshot_sources")
