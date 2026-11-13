"""split Langflow and native OpenRAG chat persistence

Revision ID: 0009_native_chat_history
Revises: 0008_session_conversation_id
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_native_chat_history"
down_revision = "0008_session_conversation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("conversations", "langflow_conversations")
    op.drop_index("ix_conversations_user_recent", table_name="langflow_conversations")
    op.drop_index("ix_conversations_user_id", table_name="langflow_conversations")
    op.create_index("ix_langflow_conversations_user_id", "langflow_conversations", ["user_id"])
    op.create_index(
        "ix_langflow_conversations_user_recent",
        "langflow_conversations",
        ["user_id", "last_activity"],
    )

    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("filter_id", sa.String(length=128), nullable=True),
        sa.Column("total_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])
    op.create_index(
        "ix_chat_conversations_user_recent",
        "chat_conversations",
        ["user_id", "last_activity"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_arguments", sa.JSON(), nullable=True),
        sa.Column("tool_result", sa.JSON(), nullable=True),
        sa.Column("event_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interrupted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"]),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_chat_messages_conversation_sequence"
        ),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index(
        "ix_chat_messages_conversation_sequence",
        "chat_messages",
        ["conversation_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_sequence", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_user_recent", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_user_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")

    op.drop_index("ix_langflow_conversations_user_recent", table_name="langflow_conversations")
    op.drop_index("ix_langflow_conversations_user_id", table_name="langflow_conversations")
    op.create_index("ix_conversations_user_id", "langflow_conversations", ["user_id"])
    op.create_index(
        "ix_conversations_user_recent",
        "langflow_conversations",
        ["user_id", "last_activity"],
    )
    op.rename_table("langflow_conversations", "conversations")
