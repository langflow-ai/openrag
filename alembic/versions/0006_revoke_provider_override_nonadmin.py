"""revoke providers:override:self from non-admin roles

Revision ID: 0006_revoke_provider_override_nonadmin
Revises: 0005_user_fk_ondelete
Create Date: 2026-06-02 00:00:00.000000

Providers are now admin-only. The 0002 seed granted ``providers:override:self``
to the built-in ``developer`` and ``user`` roles, and the seeder
(``db.seed.seed_roles_and_permissions``) is additive-only, so removing the
entry from the catalog map does not delete already-seeded rows on existing
installs. This migration deletes those two ``role_permissions`` join rows.

The permission itself stays in the catalog (admin still owns it), so only the
join rows for the two non-admin roles are removed.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_revoke_provider_override_nonadmin"
down_revision: str | Sequence[str] | None = "0005_user_fk_ondelete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERM_NAME = "providers:override:self"
_ROLE_NAMES = ["developer", "user"]


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE name = :perm) "
            "AND role_id IN (SELECT id FROM roles WHERE name IN :roles)"
        ).bindparams(
            sa.bindparam("perm", _PERM_NAME),
            sa.bindparam("roles", _ROLE_NAMES, expanding=True),
        )
    )


def downgrade() -> None:
    # Best-effort: re-grant the two join rows this migration removed.
    bind = op.get_bind()
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE name = :perm"),
        {"perm": _PERM_NAME},
    ).scalar()
    if perm_id is None:
        return
    role_ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM roles WHERE name IN :roles").bindparams(
                sa.bindparam("roles", _ROLE_NAMES, expanding=True)
            )
        ).fetchall()
    ]
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT role_id FROM role_permissions WHERE permission_id = :perm_id"),
            {"perm_id": perm_id},
        ).fetchall()
    }
    rp_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    rows = [{"role_id": rid, "permission_id": perm_id} for rid in role_ids if rid not in existing]
    if rows:
        op.bulk_insert(rp_table, rows)
