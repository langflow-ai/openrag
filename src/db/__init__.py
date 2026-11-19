"""SQL database layer for OpenRAG.

Owns users, roles, permissions, audit, preferences, api_keys.
Defaults to SQLite under data/openrag.db; switch via DATABASE_URL.
"""

from db.engine import (
    SessionLocal,
    get_engine,
    get_database_url,
    init_engine,
    dispose_engine,
)

__all__ = [
    "SessionLocal",
    "get_engine",
    "get_database_url",
    "init_engine",
    "dispose_engine",
]
