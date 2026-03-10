"""Environment variable parsing utilities."""
import os
from typing import Any, TypeVar

T = TypeVar("T")

def safe_int(val: Any, default: int) -> int:
    """Safely parse a value to an integer."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

def safe_float(val: Any, default: float) -> float:
    """Safely parse a value to a float."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def get_env_int(key: str, default: int) -> int:
    """Get an environment variable as an integer."""
    return safe_int(os.getenv(key), default)

def get_env_float(key: str, default: float) -> float:
    """Get an environment variable as a float."""
    return safe_float(os.getenv(key), default)
