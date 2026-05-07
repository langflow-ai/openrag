"""seed built-in roles and permissions

Revision ID: 0002_seed_roles_permissions
Revises: 0001_initial
Create Date: 2026-05-01 00:00:01.000000

Idempotent: re-running this migration on a database that already has rows
inserts only what's missing. Implementation lives in db.seed so the
catalog has a single source of truth.

"""
from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

from db.seed import BUILTIN_ROLES, PERMISSIONS, ROLE_PERMISSION_MAP, permission_name


revision: str = "0002_seed_roles_permissions"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()

    # Permissions
    perms_table = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("resource", sa.String),
        sa.column("action", sa.String),
        sa.column("description", sa.String),
    )
    existing_perm_names = {
        row[0] for row in bind.execute(sa.text("SELECT name FROM permissions")).fetchall()
    }
    perm_rows = []
    for resource, action, description in PERMISSIONS:
        name = permission_name(resource, action)
        if name in existing_perm_names:
            continue
        perm_rows.append(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "resource": resource,
                "action": action,
                "description": description,
            }
        )
    if perm_rows:
        op.bulk_insert(perms_table, perm_rows)

    # Roles
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    existing_role_names = {
        row[0] for row in bind.execute(sa.text("SELECT name FROM roles")).fetchall()
    }
    role_rows = []
    for role_id, role_name, description in BUILTIN_ROLES:
        if role_name in existing_role_names:
            continue
        role_rows.append(
            {
                "id": role_id,
                "name": role_name,
                "description": description,
                "is_system": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    if role_rows:
        op.bulk_insert(roles_table, role_rows)

    # Lookups for the join table
    perm_id_by_name = {
        row[1]: row[0]
        for row in bind.execute(sa.text("SELECT id, name FROM permissions")).fetchall()
    }
    role_id_by_name = {
        row[1]: row[0]
        for row in bind.execute(sa.text("SELECT id, name FROM roles")).fetchall()
    }
    existing_rp = {
        (row[0], row[1])
        for row in bind.execute(
            sa.text("SELECT role_id, permission_id FROM role_permissions")
        ).fetchall()
    }

    rp_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    rp_rows = []
    for role_name, perm_names in ROLE_PERMISSION_MAP.items():
        rid = role_id_by_name.get(role_name)
        if not rid:
            continue
        for pname in perm_names:
            pid = perm_id_by_name.get(pname)
            if not pid:
                continue
            if (rid, pid) in existing_rp:
                continue
            rp_rows.append({"role_id": rid, "permission_id": pid})
    if rp_rows:
        op.bulk_insert(rp_table, rp_rows)


def downgrade() -> None:
    # Best-effort: delete only the rows this migration would have inserted.
    bind = op.get_bind()
    role_names = [r[1] for r in BUILTIN_ROLES]
    perm_names = [permission_name(r, a) for r, a, _ in PERMISSIONS]
    if role_names:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE role_id IN "
                    "(SELECT id FROM roles WHERE name IN :names)")
            .bindparams(sa.bindparam("names", expanding=True)),
            {"names": role_names},
        )
        bind.execute(
            sa.text("DELETE FROM roles WHERE name IN :names AND is_system = 1")
            .bindparams(sa.bindparam("names", expanding=True)),
            {"names": role_names},
        )
    if perm_names:
        bind.execute(
            sa.text("DELETE FROM permissions WHERE name IN :names")
            .bindparams(sa.bindparam("names", expanding=True)),
            {"names": perm_names},
        )
