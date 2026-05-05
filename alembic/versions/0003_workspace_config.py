"""workspace_config table

Revision ID: 0003_workspace_config
Revises: 0002_seed_roles_permissions
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_workspace_config"
down_revision: Union[str, Sequence[str], None] = "0002_seed_roles_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_config",
        sa.Column("section", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"],
            name="fk_workspace_config_updated_by_users",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_config")
