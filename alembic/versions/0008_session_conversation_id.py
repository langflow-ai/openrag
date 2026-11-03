"""Persist canonical conversation IDs for session aliases.

Revision ID: 0008_session_conversation_id
Revises: 0007_add_knowledge_delete_anonymous
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_session_conversation_id"
down_revision = "0007_add_knowledge_delete_anonymous"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_ownership", sa.Column("conversation_id", sa.String(64), nullable=True))
    op.create_index(
        "ix_session_ownership_conversation_id", "session_ownership", ["conversation_id"]
    )
    op.execute("UPDATE session_ownership SET conversation_id = response_id")


def downgrade() -> None:
    with op.batch_alter_table("session_ownership") as batch:
        batch.drop_index("ix_session_ownership_conversation_id")
        batch.drop_column("conversation_id")
