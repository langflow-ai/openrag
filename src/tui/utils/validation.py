"""Input validation utilities for TUI."""

import os
import re
from pathlib import Path
from typing import Optional


class ValidationError(Exception):
    """Validation error exception."""

    pass


def validate_env_var_name(name: str) -> bool:
    """Validate environment variable name format."""
    return bool(re.match(r"^[A-Z][A-Z0-9_]*$", name))


def validate_path(
    path: str, must_exist: bool = False, must_be_dir: bool = False
) -> bool:
    """Validate file/directory path."""
    if not path:
        return False

    try:
        path_obj = Path(path).expanduser().resolve()

        if must_exist and not path_obj.exists():
            return False

        if must_be_dir and path_obj.exists() and not path_obj.is_dir():
            return False

        return True
    except (OSError, ValueError):
        return False


def validate_url(url: str) -> bool:
    """Validate URL format."""
    if not url:
        return False

    url_pattern = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    return bool(url_pattern.match(url))


def validate_openai_api_key(key: str) -> bool:
    """Validate OpenAI API key format."""
    if not key:
        return False
    return key.startswith("sk-") and len(key) > 20


def validate_google_oauth_client_id(client_id: str) -> bool:
    """Validate Google OAuth client ID format."""
    if not client_id:
        return False
    return client_id.endswith(".apps.googleusercontent.com")


def validate_non_empty(value: str) -> bool:
    """Validate that value is not empty."""
    return bool(value and value.strip())


def sanitize_env_value(value: str) -> str:
    """Sanitize environment variable value."""
    # Remove leading/trailing whitespace
    value = value.strip()

    # Remove quotes if they wrap the entire value
    if len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

    return value


def validate_documents_paths(paths_str: str) -> tuple[bool, str, list[str]]:
    """
    Validate comma-separated documents paths for volume mounting.

    Returns:
        (is_valid, error_message, validated_paths)
    """
    if not paths_str:
        return False, "Documents paths cannot be empty", []

    paths = [path.strip() for path in paths_str.split(",") if path.strip()]

    if not paths:
        return False, "No valid paths provided", []

    validated_paths = []

    for path in paths:
        try:
            path_obj = Path(path).expanduser().resolve()

            # Check if path exists
            if not path_obj.exists():
                # Try to create it
                try:
                    path_obj.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    return False, f"Cannot create directory '{path}': {e}", []

            # Check if it's a directory
            if not path_obj.is_dir():
                return False, f"Path '{path}' must be a directory", []

            # Check if we can write to it
            try:
                test_file = path_obj / ".openrag_test"
                test_file.touch()
                test_file.unlink()
            except (OSError, PermissionError):
                return False, f"Directory '{path}' is not writable", []

            validated_paths.append(str(path_obj))

        except (OSError, ValueError) as e:
            return False, f"Invalid path '{path}': {e}", []

    return True, "All paths valid", validated_paths
