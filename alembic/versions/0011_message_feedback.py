"""add message_feedback

Revision ID: 0011_message_feedback
Revises: 0010_move_legacy_native_chat
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_message_feedback"
down_revision = "0010_move_legacy_native_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("model_provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("retrieval", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "message_id", name="uq_message_feedback_user_message"),
        sa.CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating"),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) <= 2000",
            name="ck_message_feedback_comment_length",
        ),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"])
    op.create_index("ix_message_feedback_created", "message_feedback", ["created_at", "id"])
    op.create_index(
        "ix_message_feedback_rating_created", "message_feedback", ["rating", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_message_feedback_rating_created", table_name="message_feedback")
    op.drop_index("ix_message_feedback_created", table_name="message_feedback")
    op.drop_index("ix_message_feedback_user_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_id", table_name="message_feedback")
    op.drop_table("message_feedback")
