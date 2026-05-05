"""SQLModel metadata + naming convention.

Naming convention is required for Alembic to autogenerate stable
constraint names across SQLite and Postgres.
"""

from sqlalchemy import MetaData
from sqlmodel import SQLModel

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
SQLModel.metadata.naming_convention = NAMING_CONVENTION  # type: ignore[attr-defined]
