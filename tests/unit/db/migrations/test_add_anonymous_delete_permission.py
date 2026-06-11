"""Tests for the anonymous document-delete permission migration."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0007_add_knowledge_delete_anonymous.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0007", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_is_idempotent_and_preserves_delete_any(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    roles = sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, unique=True, nullable=False),
    )
    permissions = sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, unique=True, nullable=False),
        sa.Column("resource", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("description", sa.String),
    )
    role_permissions = sa.Table(
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.String, primary_key=True),
        sa.Column("permission_id", sa.String, primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            roles.insert(),
            [
                {"id": "role-admin", "name": "admin"},
                {"id": "role-custom", "name": "custom"},
            ],
        )
        connection.execute(
            permissions.insert(),
            {
                "id": "perm-delete-any",
                "name": "knowledge:delete:any",
                "resource": "knowledge",
                "action": "delete:any",
                "description": "Delete any document",
            },
        )
        connection.execute(
            role_permissions.insert(),
            {"role_id": "role-custom", "permission_id": "perm-delete-any"},
        )

        migration = _load_migration()
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        migration.upgrade()

        permission_rows = connection.execute(
            sa.text(
                "SELECT id, name FROM permissions "
                "WHERE name IN ('knowledge:delete:any', 'knowledge:delete:anonymous') "
                "ORDER BY name"
            )
        ).fetchall()
        assert [row.name for row in permission_rows] == [
            "knowledge:delete:anonymous",
            "knowledge:delete:any",
        ]

        anonymous_id = next(
            row.id for row in permission_rows if row.name == "knowledge:delete:anonymous"
        )
        assignments = connection.execute(
            sa.text(
                "SELECT role_id, permission_id FROM role_permissions "
                "ORDER BY role_id, permission_id"
            )
        ).fetchall()
        assert ("role-admin", anonymous_id) in assignments
        assert ("role-custom", "perm-delete-any") in assignments
        assert len([row for row in assignments if row == ("role-admin", anonymous_id)]) == 1
