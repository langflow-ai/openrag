"""SQL database layer for BomaRAG.

Owns users, roles, permissions, audit, preferences, api_keys.
Defaults to SQLite under data/bomarag.db; switch via DATABASE_URL.
"""

from db.engine import (
    SessionLocal,
    dispose_engine,
    get_database_url,
    get_engine,
    init_engine,
)

__all__ = [
    "SessionLocal",
    "get_engine",
    "get_database_url",
    "init_engine",
    "dispose_engine",
]
