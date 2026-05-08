"""apply ondelete= policy to user FKs

Revision ID: 0005_user_fk_ondelete
Revises: 0004_chat_history_tables
Create Date: 2026-05-05 00:00:00.000000

Background:
    The initial schema (0001_initial) declared FKs to ``users.id`` from
    ``user_roles``, ``user_preferences``, ``api_keys``, ``audit_log``,
    and ``workspace_config`` (added in 0003) — all without an
    ``ondelete=`` clause. SQLite doesn't enforce FKs by default so this
    is invisible there, but Postgres enforces RESTRICT, so a
    ``DELETE FROM users WHERE id = ?`` raises an IntegrityError on the
    very first admin-deletes-user request.

Policy applied here:
    user_roles.user_id           CASCADE   (owned membership)
    user_roles.granted_by        SET NULL  (audit ref — keep the row)
    user_preferences.user_id     CASCADE   (owned data)
    api_keys.user_id             CASCADE   (owned credential)
    audit_log.actor_user_id      SET NULL  (preserve audit trail)
    workspace_config.updated_by  SET NULL  (preserve change history)

Implementation note:
    Uses batch_alter_table for SQLite compatibility (recreates the
    table with the new FK definitions). Postgres applies the change in
    place via ALTER TABLE inside the same op.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005_user_fk_ondelete"
down_revision: Union[str, Sequence[str], None] = "0004_chat_history_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_POLICY = [
    # (table, fk_name, local_cols, remote_table, remote_cols, ondelete)
    ("user_roles", "fk_user_roles_user_id_users",
     ["user_id"], "users", ["id"], "CASCADE"),
    ("user_roles", "fk_user_roles_granted_by_users",
     ["granted_by"], "users", ["id"], "SET NULL"),
    ("user_preferences", "fk_user_preferences_user_id_users",
     ["user_id"], "users", ["id"], "CASCADE"),
    ("api_keys", "fk_api_keys_user_id_users",
     ["user_id"], "users", ["id"], "CASCADE"),
    ("audit_log", "fk_audit_log_actor_user_id_users",
     ["actor_user_id"], "users", ["id"], "SET NULL"),
    ("workspace_config", "fk_workspace_config_updated_by_users",
     ["updated_by"], "users", ["id"], "SET NULL"),
]


def upgrade() -> None:
    for table, name, cols, ref_table, ref_cols, ondelete in _FK_POLICY:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(
                name, ref_table, cols, ref_cols, ondelete=ondelete
            )


def downgrade() -> None:
    for table, name, cols, ref_table, ref_cols, _ondelete in _FK_POLICY:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(name, ref_table, cols, ref_cols)
