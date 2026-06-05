"""seed connectors:manage:access permission and grant it to admin

Revision ID: 0007_seed_connectors_manage_access
Revises: 0006_revoke_provider_override_nonadmin
Create Date: 2026-06-04 00:00:00.000000

Idempotent: inserts the permission row and the admin role grant only when
missing. The catalog lives in db.seed so fresh installs/tests pick this up via
seed_roles_and_permissions; this migration backfills existing databases.

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_seed_connectors_manage_access"
down_revision: str | Sequence[str] | None = "0006_revoke_provider_override_nonadmin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE = "connectors"
_ACTION = "manage:access"
_DESCRIPTION = "Manage which connectors non-admin users may use"
# Frozen at migration time — matches db.seed.permission_name(resource, action).
_PERM_NAME = f"{_RESOURCE}:{_ACTION}"
_ADMIN_ROLE = "admin"


def upgrade() -> None:
    bind = op.get_bind()

    # Insert the permission if missing.
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name").bindparams(
            sa.bindparam("name", _PERM_NAME)
        )
    ).scalar()
    if perm_id is None:
        perm_id = str(uuid.uuid4())
        op.bulk_insert(
            sa.table(
                "permissions",
                sa.column("id", sa.String),
                sa.column("name", sa.String),
                sa.column("resource", sa.String),
                sa.column("action", sa.String),
                sa.column("description", sa.String),
            ),
            [
                {
                    "id": perm_id,
                    "name": _PERM_NAME,
                    "resource": _RESOURCE,
                    "action": _ACTION,
                    "description": _DESCRIPTION,
                }
            ],
        )

    # Grant it to the admin role if missing.
    admin_role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE name = :name").bindparams(
            sa.bindparam("name", _ADMIN_ROLE)
        )
    ).scalar()
    if admin_role_id is None:
        return

    already_granted = bind.execute(
        sa.text(
            "SELECT 1 FROM role_permissions WHERE role_id = :role_id AND permission_id = :perm_id"
        ).bindparams(
            sa.bindparam("role_id", admin_role_id),
            sa.bindparam("perm_id", perm_id),
        )
    ).scalar()
    if already_granted is None:
        op.bulk_insert(
            sa.table(
                "role_permissions",
                sa.column("role_id", sa.String),
                sa.column("permission_id", sa.String),
            ),
            [{"role_id": admin_role_id, "permission_id": perm_id}],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE name = :name)"
        ).bindparams(sa.bindparam("name", _PERM_NAME))
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE name = :name").bindparams(
            sa.bindparam("name", _PERM_NAME)
        )
    )
