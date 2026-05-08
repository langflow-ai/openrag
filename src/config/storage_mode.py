"""Single source of truth for OpenRAG's storage-mode flag.

Three modes — one env var, no per-domain proliferation:

    OPENRAG_STORAGE_MODE = db | hybrid | files

| Mode    | DB writes | File writes | File reads (fallback) | When to use                          |
|---------|-----------|-------------|-----------------------|--------------------------------------|
| db      | yes       | NO          | no                    | default — DB is sole authority       |
| hybrid  | yes       | yes         | yes                   | Phase B dual-write (legacy fallback) |
| files   | NO        | yes         | yes                   | rollback / legacy installs           |

Backwards compat: the legacy ``OPENRAG_DISABLE_DB_WORKSPACE_CONFIG=true``
kill switch is still honored — if set, mode is forced to ``files``.

``workspace_config``, ``session_ownership`` and ``conversations`` all
consult this flag. The default is now ``db`` so fresh installs never
write JSON state to disk. Existing installs with JSON files are
upgraded once at boot via the runtime migrations
(``config_yaml_to_db_v1``, ``chat_history_json_to_db_v1``); after that
the JSON files are ignored.
"""

from __future__ import annotations

import os
from typing import Literal

StorageMode = Literal["hybrid", "db", "files"]

_VALID = {"hybrid", "db", "files"}
_DEFAULT: StorageMode = "db"


def get_storage_mode() -> StorageMode:
    """Resolve the active storage mode. Returns one of: hybrid, db, files."""
    # Legacy kill switch wins if explicitly set — operators may have it
    # baked into their deployment manifests.
    if os.getenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", "").lower() in (
        "true", "1", "yes",
    ):
        return "files"

    raw = (os.getenv("OPENRAG_STORAGE_MODE") or _DEFAULT).strip().lower()
    if raw not in _VALID:
        return _DEFAULT
    return raw  # type: ignore[return-value]


def db_writes_enabled() -> bool:
    return get_storage_mode() in ("hybrid", "db")


def file_writes_enabled() -> bool:
    return get_storage_mode() in ("hybrid", "files")


def file_reads_allowed() -> bool:
    """In `db` mode we deliberately ignore yaml/JSON files even if present.
    Hybrid + files modes both consult them."""
    return get_storage_mode() in ("hybrid", "files")
