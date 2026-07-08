"""add knowledge:delete:anonymous permission

Revision ID: 0007_add_knowledge_delete_anonymous
Revises: 0006_revoke_provider_override_nonadmin
Create Date: 2026-06-11 00:00:00.000000

Adds a dedicated permission for deleting ownerless shared documents and grants
it to the built-in admin role. The existing knowledge:delete:any permission is
left unchanged.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_add_knowledge_delete_anonymous"
down_revision: str | Sequence[str] | None = "0006_revoke_provider_override_nonadmin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION_NAME = "knowledge:delete:anonymous"
_ADMIN_ROLE_NAME = "admin"


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name"),
        {"name": _PERMISSION_NAME},
    ).scalar()

    if permission_id is None:
        permission_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO permissions "
                "(id, name, resource, action, description) "
                "VALUES (:id, :name, :resource, :action, :description)"
            ),
            {
                "id": permission_id,
                "name": _PERMISSION_NAME,
                "resource": "knowledge",
                "action": "delete:anonymous",
                "description": "Delete anonymous shared documents",
            },
        )

    admin_role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE name = :name"),
        {"name": _ADMIN_ROLE_NAME},
    ).scalar()
    if admin_role_id is None:
        return

    existing = bind.execute(
        sa.text(
            "SELECT 1 FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": admin_role_id, "permission_id": permission_id},
    ).first()
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": admin_role_id, "permission_id": permission_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name"),
        {"name": _PERMISSION_NAME},
    ).scalar()
    if permission_id is None:
        return

    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id"),
        {"permission_id": permission_id},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE id = :permission_id"),
        {"permission_id": permission_id},
    )
