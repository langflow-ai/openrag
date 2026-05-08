"""chat history tables (session_ownership + conversations)

Revision ID: 0004_chat_history_tables
Revises: 0003_workspace_config
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_chat_history_tables"
down_revision: Union[str, Sequence[str], None] = "0003_workspace_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_ownership",
        sa.Column("response_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_session_ownership_user_id", "session_ownership", ["user_id"]
    )

    op.create_table(
        "conversations",
        sa.Column("response_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("endpoint", sa.String(length=64), nullable=True),
        sa.Column("previous_response_id", sa.String(length=64), nullable=True),
        sa.Column("filter_id", sa.String(length=128), nullable=True),
        sa.Column("total_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index(
        "ix_conversations_user_recent",
        "conversations",
        ["user_id", "last_activity"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_recent", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_session_ownership_user_id", table_name="session_ownership")
    op.drop_table("session_ownership")
