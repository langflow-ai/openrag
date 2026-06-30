# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

"""SQL database layer for OpenRAG.

Owns users, roles, permissions, audit, preferences, api_keys.
Defaults to SQLite under data/openrag.db; switch via DATABASE_URL.
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
