"""move legacy /chat metadata into native history tables

Revision ID: 0010_move_legacy_native_chat_history
Revises: 0009_native_chat_history
"""

from alembic import op

revision = "0010_move_legacy_native_chat_history"
down_revision = "0009_native_chat_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move legacy native-chat metadata out of Langflow's table."""
    # Revision 0009 split the old shared conversations table. Existing rows
    # labelled `chat` belonged to the pre-split native endpoint, not Langflow.
    # Copy first to keep this safe when a partial/manual migration already
    # created a native row, then remove the misplaced source row.
    op.execute(
        """
        INSERT INTO chat_conversations
            (id, user_id, title, filter_id, total_messages, created_at, last_activity)
        SELECT response_id, user_id, title, filter_id, total_messages, created_at, last_activity
        FROM langflow_conversations AS legacy
        WHERE endpoint = 'chat'
          AND NOT EXISTS (
              SELECT 1 FROM chat_conversations AS native
              WHERE native.id = legacy.response_id
          )
        """
    )
    op.execute("DELETE FROM langflow_conversations WHERE endpoint = 'chat'")


def downgrade() -> None:
    """Restore legacy native-chat metadata after removing dependent messages."""
    op.execute(
        """
        INSERT INTO langflow_conversations
            (response_id, user_id, title, endpoint, previous_response_id, filter_id,
             total_messages, created_at, last_activity)
        SELECT id, user_id, title, 'chat', NULL, filter_id, total_messages, created_at, last_activity
        FROM chat_conversations AS native
        WHERE NOT EXISTS (
            SELECT 1 FROM langflow_conversations AS legacy
            WHERE legacy.response_id = native.id
        )
        """
    )
    # Revision 0009 keeps ``chat_messages.conversation_id`` as a foreign key
    # to ``chat_conversations.id``. Delete dependent rows before their parent
    # rows so a downgrade works for native chats which have already been used.
    op.execute(
        "DELETE FROM chat_messages "
        "WHERE conversation_id IN (SELECT id FROM chat_conversations)"
    )
    op.execute("DELETE FROM chat_conversations")
