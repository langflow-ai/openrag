"""Environment variable parsing utilities."""

import os
from typing import Any, TypeVar

T = TypeVar("T")


def safe_int(val: Any, default: int | None = None) -> int | None:
    """Safely parse a value to an integer."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def safe_float(val: Any, default: float | None = None) -> float | None:
    """Safely parse a value to a float."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def get_env_int(key: str, default: int | None = None) -> int | None:
    """Get an environment variable as an integer."""
    return safe_int(os.getenv(key), default)


def get_env_float(key: str, default: float | None = None) -> float | None:
    """Get an environment variable as a float."""
    return safe_float(os.getenv(key), default)


def get_env_set(key: str) -> set[str] | None:
    """Return a set of non-empty strings from a comma-separated env var.

    Returns None (not an empty set) when the variable is absent or blank,
    so callers can distinguish 'unset = skip check' from 'set-but-empty = block all'.
    """
    raw = os.getenv(key, "").strip()
    if not raw:
        return None
    return {v.strip() for v in raw.split(",") if v.strip()}
