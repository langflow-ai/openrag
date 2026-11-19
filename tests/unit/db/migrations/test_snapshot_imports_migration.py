"""Alembic 0011: snapshot source/import/dataset registry tables."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

import db.models  # noqa: F401 - registers the tables on SQLModel.metadata

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0011_snapshot_imports.py"
TABLES = ("snapshot_sources", "snapshot_imports", "snapshot_datasets")


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0011", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def connection():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def _run(connection, fn_name: str) -> None:
    migration = _load_migration()
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, fn_name)()


def test_revision_chain_has_a_single_head():
    migration = _load_migration()
    assert migration.revision == "0011_snapshot_imports"
    assert migration.down_revision == "0010_move_legacy_native_chat"

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0011_snapshot_imports"]


def test_upgrade_creates_tables_indexes_and_keys(connection):
    _run(connection, "upgrade")
    inspector = sa.inspect(connection)

    assert set(TABLES) <= set(inspector.get_table_names())
    imports_indexes = {ix["name"]: ix for ix in inspector.get_indexes("snapshot_imports")}
    assert imports_indexes["ix_snapshot_imports_slug"]["unique"]
    assert "ix_snapshot_imports_owner_user_id" in imports_indexes
    assert "ix_snapshot_sources_owner_user_id" in {
        ix["name"] for ix in inspector.get_indexes("snapshot_sources")
    }

    (source_fk,) = inspector.get_foreign_keys("snapshot_imports")
    assert source_fk["referred_table"] == "snapshot_sources"
    assert source_fk["options"].get("ondelete") == "RESTRICT"
    (import_fk,) = inspector.get_foreign_keys("snapshot_datasets")
    assert import_fk["referred_table"] == "snapshot_imports"
    assert import_fk["options"].get("ondelete") == "CASCADE"
    uniques = inspector.get_unique_constraints("snapshot_datasets")
    assert {tuple(u["column_names"]) for u in uniques} == {("import_id", "ordinal")}


def test_upgraded_schema_matches_the_orm_models(connection):
    _run(connection, "upgrade")
    inspector = sa.inspect(connection)
    for table in TABLES:
        migrated = {c["name"]: c for c in inspector.get_columns(table)}
        modelled = SQLModel.metadata.tables[table].columns
        assert set(migrated) == {c.name for c in modelled}, table
        for column in modelled:
            assert migrated[column.name]["nullable"] == column.nullable, (table, column.name)


def test_recovery_columns_are_migrated(connection):
    """Publication intent and reserved attempt generations survive restarts (B3/B5)."""
    _run(connection, "upgrade")
    columns = {c["name"]: c for c in sa.inspect(connection).get_columns("snapshot_imports")}

    assert columns["attempt_generation"]["nullable"] is False
    assert columns["pending_publication"]["nullable"] is True


def test_cascade_removes_datasets_and_restrict_protects_sources(connection):
    _run(connection, "upgrade")
    connection.execute(sa.text("PRAGMA foreign_keys=ON"))
    now = "2026-01-01 00:00:00"
    connection.execute(
        sa.text(
            "INSERT INTO snapshot_sources (id, owner_user_id, name, region, bucket, prefix, path_style, verify_tls,"
            " created_at, updated_at) VALUES ('s1','u1','src','us-east-1','b','',1,1,:n,:n)"
        ),
        {"n": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO snapshot_imports (id, slug, name, source_id, owner_user_id, shared, snapshot_name,"
            " snapshot_uuid, source_indices, staged_bytes, status, generation, attempt_generation, job_state,"
            " job_kind, analyser_inlines, created_at, updated_at) VALUES ('i1','abcdefghij','imp','s1','u1',0,'snap',"
            " 'uuid', '[]', 10737418240, 'staging', 1, 0, 'idle', 'import', '{}', :n, :n)"
        ),
        {"n": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO snapshot_datasets (id, import_id, ordinal, source_index, index_alias, concrete_index,"
            " display_name, description, field_map, retrieval, doc_count, created_at, updated_at)"
            " VALUES ('d1','i1',0,'idx','ds_abcdefghij_0','ds_abcdefghij_0_g1','idx','', '{}', '{}', 0, :n, :n)"
        ),
        {"n": now},
    )

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("DELETE FROM snapshot_sources WHERE id='s1'"))
    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(
            sa.text(
                "INSERT INTO snapshot_datasets (id, import_id, ordinal, source_index,"
                " index_alias, concrete_index, display_name, description, field_map,"
                " retrieval, doc_count, created_at, updated_at) VALUES ('d2','i1',0,'x','a','b',"
                "'x','','{}','{}',0,'2026-01-01','2026-01-01')"
            )
        )
    connection.execute(sa.text("DELETE FROM snapshot_imports WHERE id='i1'"))
    assert connection.execute(sa.text("SELECT COUNT(*) FROM snapshot_datasets")).scalar_one() == 0


def test_downgrade_removes_everything_and_is_repeatable(connection):
    _run(connection, "upgrade")
    _run(connection, "downgrade")
    assert not set(TABLES) & set(sa.inspect(connection).get_table_names())

    _run(connection, "upgrade")
    assert set(TABLES) <= set(sa.inspect(connection).get_table_names())
