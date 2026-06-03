"""seed connectors:manage:global permission and grant to admin

Revision ID: 0007_seed_connectors_manage_global
Revises: 0006_revoke_provider_override_nonadmin
Create Date: 2026-06-03 00:00:00.000000

Adds the admin-only ``connectors:manage:global`` permission (workspace-wide
enable/disable of connectors) and grants it to the built-in ``admin`` role.

Idempotent: skips the permission row if it already exists and skips the
``admin`` join row if it is already present. Mirrors the sync insert pattern
in ``0002_seed_roles_permissions``.

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_seed_connectors_manage_global"
down_revision: str | Sequence[str] | None = "0006_revoke_provider_override_nonadmin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERM_NAME = "connectors:manage:global"
_PERM_RESOURCE = "connectors"
_PERM_ACTION = "manage:global"
_PERM_DESCRIPTION = "Enable/disable connectors workspace-wide"
_ROLE_NAME = "admin"


def upgrade() -> None:
    bind = op.get_bind()

    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name"),
        {"name": _PERM_NAME},
    ).scalar()

    if perm_id is None:
        perm_id = str(uuid.uuid4())
        perms_table = sa.table(
            "permissions",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("resource", sa.String),
            sa.column("action", sa.String),
            sa.column("description", sa.String),
        )
        op.bulk_insert(
            perms_table,
            [
                {
                    "id": perm_id,
                    "name": _PERM_NAME,
                    "resource": _PERM_RESOURCE,
                    "action": _PERM_ACTION,
                    "description": _PERM_DESCRIPTION,
                }
            ],
        )

    role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE name = :name"),
        {"name": _ROLE_NAME},
    ).scalar()
    if role_id is None:
        return

    already_granted = bind.execute(
        sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
        {"rid": role_id, "pid": perm_id},
    ).scalar()
    if already_granted is None:
        rp_table = sa.table(
            "role_permissions",
            sa.column("role_id", sa.String),
            sa.column("permission_id", sa.String),
        )
        op.bulk_insert(rp_table, [{"role_id": role_id, "permission_id": perm_id}])


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE name = :name)"
        ).bindparams(sa.bindparam("name", _PERM_NAME))
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE name = :name").bindparams(
            sa.bindparam("name", _PERM_NAME)
        )
    )
