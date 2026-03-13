"""Environment variable parsing utilities.

This module provides type-safe utilities for parsing environment variables
with sensible defaults and error handling.
"""
import os
from typing import Any, Optional, TypeVar, Union, overload

T = TypeVar("T")


def safe_int(val: Any, default: int) -> int:
    """Safely parse a value to an integer.
    
    Args:
        val: Value to parse (string, int, or None)
        default: Default value if parsing fails or value is None/empty
        
    Returns:
        Parsed integer or default value
    """
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def safe_float(val: Any, default: float) -> float:
    """Safely parse a value to a float.
    
    Args:
        val: Value to parse (string, float, int, or None)
        default: Default value if parsing fails or value is None/empty
        
    Returns:
        Parsed float or default value
    """
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_bool(val: Any, default: bool) -> bool:
    """Safely parse a value to a boolean.
    
    Recognizes common truthy/falsy string values:
    - Truthy: 'true', '1', 'yes', 'on', 'enabled' (case-insensitive)
    - Falsy: 'false', '0', 'no', 'off', 'disabled' (case-insensitive)
    
    Args:
        val: Value to parse (string, bool, int, or None)
        default: Default value if parsing fails or value is None/empty
        
    Returns:
        Parsed boolean or default value
    """
    if val is None or val == "":
        return default
    
    if isinstance(val, bool):
        return val
    
    if isinstance(val, (int, float)):
        return bool(val)
    
    if isinstance(val, str):
        val_lower = val.lower().strip()
        if val_lower in ("true", "1", "yes", "on", "enabled"):
            return True
        if val_lower in ("false", "0", "no", "off", "disabled"):
            return False
    
    return default


def get_env_int(key: str, default: int) -> int:
    """Get an environment variable as an integer.
    
    Args:
        key: Environment variable name
        default: Default value if not set or invalid
        
    Returns:
        Parsed integer or default value
    """
    return safe_int(os.getenv(key), default)


def get_env_float(key: str, default: float) -> float:
    """Get an environment variable as a float.
    
    Args:
        key: Environment variable name
        default: Default value if not set or invalid
        
    Returns:
        Parsed float or default value
    """
    return safe_float(os.getenv(key), default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get an environment variable as a boolean.
    
    Args:
        key: Environment variable name
        default: Default value if not set (default: False)
        
    Returns:
        Parsed boolean or default value
        
    Example:
        >>> # With OPENRAG_DEBUG=true
        >>> get_env_bool("OPENRAG_DEBUG")  # Returns True
        
        >>> # With OPENRAG_DEBUG=0
        >>> get_env_bool("OPENRAG_DEBUG")  # Returns False
        
        >>> # With unset variable
        >>> get_env_bool("OPENRAG_DEBUG", default=True)  # Returns True
    """
    return safe_bool(os.getenv(key), default)


def get_env_str(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an environment variable as a string.
    
    Args:
        key: Environment variable name
        default: Default value if not set (default: None)
        
    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default)


def get_env_list(key: str, default: Optional[list[str]] = None, separator: str = ",") -> list[str]:
    """Get an environment variable as a list of strings.
    
    Splits the environment variable value by the specified separator.
    
    Args:
        key: Environment variable name
        default: Default list if not set (default: empty list)
        separator: Character to split on (default: comma)
        
    Returns:
        List of strings or default value
        
    Example:
        >>> # With OPENRAG_HOSTS=localhost,127.0.0.1
        >>> get_env_list("OPENRAG_HOSTS")  # Returns ['localhost', '127.0.0.1']
    """
    val = os.getenv(key)
    if val is None or val == "":
        return default or []
    return [item.strip() for item in val.split(separator) if item.strip()]


def get_env_dict(
    key: str,
    default: Optional[dict[str, str]] = None,
    pair_separator: str = ",",
    kv_separator: str = "="
) -> dict[str, str]:
    """Get an environment variable as a dictionary.
    
    Parses key-value pairs from the environment variable.
    
    Args:
        key: Environment variable name
        default: Default dict if not set (default: empty dict)
        pair_separator: Character separating key-value pairs (default: comma)
        kv_separator: Character separating key from value (default: equals)
        
    Returns:
        Dictionary of key-value pairs or default value
        
    Example:
        >>> # With OPENRAG_CONFIG=key1=val1,key2=val2
        >>> get_env_dict("OPENRAG_CONFIG")  # Returns {'key1': 'val1', 'key2': 'val2'}
    """
    val = os.getenv(key)
    if val is None or val == "":
        return default or {}
    
    result = {}
    for pair in val.split(pair_separator):
        if kv_separator in pair:
            k, v = pair.split(kv_separator, 1)
            result[k.strip()] = v.strip()
    return result


def require_env(key: str, description: Optional[str] = None) -> str:
    """Get a required environment variable.
    
    Raises a descriptive error if the variable is not set.
    
    Args:
        key: Environment variable name
        description: Optional description of the variable for error message
        
    Returns:
        Environment variable value
        
    Raises:
        ValueError: If the environment variable is not set
        
    Example:
        >>> require_env("OPENRAG_API_KEY", "Your OpenRAG API key")
        ValueError: Required environment variable 'OPENRAG_API_KEY' is not set. Your OpenRAG API key
    """
    val = os.getenv(key)
    if val is None or val == "":
        error_msg = f"Required environment variable '{key}' is not set."
        if description:
            error_msg += f" {description}"
        raise ValueError(error_msg)
    return val
