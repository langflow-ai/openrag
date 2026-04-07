"""Centralized path helpers for OpenRAG.

This module is the single source of truth for the OPENRAG_*_PATH environment variables.
Variables are read directly via ``os.getenv`` here to avoid circular imports
(settings → config_manager → paths → settings).
"""

import os


# ---------------------------------------------------------------------------
# Documents directory
# ---------------------------------------------------------------------------
def get_documents_path() -> str:
    """Return the path to the documents directory.

    Environment variable: OPENRAG_DOCUMENTS_PATH
    Default: ``openrag-documents``  (relative to the working directory)
    """
    return os.getenv("OPENRAG_DOCUMENTS_PATH") or "openrag-documents"


# ---------------------------------------------------------------------------
# JWT keys directory
# ---------------------------------------------------------------------------
def get_keys_path() -> str:
    """Return the path to the JWT keys directory.

    Environment variable: OPENRAG_KEYS_PATH
    Default: ``keys``  (relative to the working directory)
    """
    return os.getenv("OPENRAG_KEYS_PATH") or "keys"


# ---------------------------------------------------------------------------
# Flows directory
# ---------------------------------------------------------------------------
def get_flows_path() -> str:
    """Return the path to the flows directory.

    Environment variable: OPENRAG_FLOWS_PATH
    Default: ``flows``  (relative to the working directory)
    """
    return os.getenv("OPENRAG_FLOWS_PATH") or "flows"


def get_flows_backup_path() -> str:
    """Return the path to the flows backup directory.

    Environment variable: OPENRAG_FLOWS_BACKUP_PATH
    Default: ``<flows_path>/backup``
    """
    return os.getenv("OPENRAG_FLOWS_BACKUP_PATH") or os.path.join(get_flows_path(), "backup")


# ---------------------------------------------------------------------------
# Config directory (holds config.yaml)
# ---------------------------------------------------------------------------
def get_config_path() -> str:
    """Return the path to the configuration directory.

    Environment variable: OPENRAG_CONFIG_PATH
    Default: ``config``  (relative to the working directory)
    """
    return os.getenv("OPENRAG_CONFIG_PATH") or "config"


def get_config_file_path() -> str:
    """Return the full path to the config.yaml file."""
    return os.path.join(get_config_path(), "config.yaml")


# ---------------------------------------------------------------------------
# Data directory (conversations, tokens, connections, etc.)
# ---------------------------------------------------------------------------
def get_data_path() -> str:
    """Return the path to the data directory.

    Environment variable: OPENRAG_DATA_PATH
    Default: ``data``  (relative to the working directory)
    """
    return os.getenv("OPENRAG_DATA_PATH") or "data"


def get_data_file(filename: str) -> str:
    """Return a full path for a file inside the data directory.

    Example::

        get_data_file("conversations.json")
        # → "data/conversations.json"  (or $OPENRAG_DATA_PATH/conversations.json)
    """
    return os.path.join(get_data_path(), filename)
