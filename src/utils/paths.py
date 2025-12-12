"""Centralized path management for OpenRAG.

This module provides functions to get standardized paths for OpenRAG files and directories.
All paths are centralized under ~/.openrag/ to avoid cluttering the user's current working directory.
"""

import os
from pathlib import Path
from utils.logging_config import get_logger
from utils.container_utils import detect_container_environment

logger = get_logger(__name__)


def get_openrag_home() -> Path:
    """Get the OpenRAG home directory.
    
    In containers: Uses current working directory (for backward compatibility)
    In local environments: Uses ~/.openrag/
    
    Returns:
        Path to OpenRAG home directory
    """
    # In container environments, use the container's working directory
    # This maintains backward compatibility with existing Docker setups
    container_env = detect_container_environment()
    if container_env:
        # In containers, return the container's working directory.
        # This ensures compatibility with existing Docker volume mounts,
        # as Docker typically mounts volumes into the working directory.
        return Path.cwd()
    
    # In local environments, use centralized location
    home_dir = Path.home() / ".openrag"
    home_dir.mkdir(parents=True, exist_ok=True)
    return home_dir


def get_config_dir() -> Path:
    """Get the configuration directory.
    
    Returns:
        Path to config directory (~/.openrag/config/ or ./config/ in containers)
    """
    config_dir = get_openrag_home() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file() -> Path:
    """Get the configuration file path.
    
    Returns:
        Path to config.yaml file
    """
    return get_config_dir() / "config.yaml"


def get_keys_dir() -> Path:
    """Get the JWT keys directory.
    
    Returns:
        Path to keys directory (~/.openrag/keys/ or ./keys/ in containers)
    """
    keys_dir = get_openrag_home() / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    return keys_dir


def get_private_key_path() -> Path:
    """Get the JWT private key path.
    
    Returns:
        Path to private_key.pem
    """
    return get_keys_dir() / "private_key.pem"


def get_public_key_path() -> Path:
    """Get the JWT public key path.
    
    Returns:
        Path to public_key.pem
    """
    return get_keys_dir() / "public_key.pem"


def get_documents_dir() -> Path:
    """Get the documents directory for default document ingestion.
    
    In containers: Uses /app/openrag-documents (Docker volume mount)
    In local environments: Uses ~/.openrag/documents/openrag-documents
    
    Returns:
        Path to documents directory
    """
    container_env = detect_container_environment()
    if container_env:
        # In containers, use the Docker volume mount path
        return Path("/app/openrag-documents")
    
    # In local environments, use centralized location
    documents_dir = get_openrag_home() / "documents" / "openrag-documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    return documents_dir


def get_flows_dir() -> Path:
    """Get the flows directory.
    
    Returns:
        Path to flows directory (~/.openrag/flows/ or ./flows/ in containers)
    """
    flows_dir = get_openrag_home() / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    return flows_dir


def get_flows_backup_dir() -> Path:
    """Get the flows backup directory.
    
    Returns:
        Path to flows/backup directory
    """
    backup_dir = get_flows_dir() / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_data_dir() -> Path:
    """Get the data directory.
    
    Returns:
        Path to data directory (~/.openrag/data/ or ./data/ in containers)
    """
    data_dir = get_openrag_home() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_opensearch_data_dir() -> Path:
    """Get the OpenSearch data directory.
    
    Returns:
        Path to OpenSearch data directory
    """
    return get_data_dir() / "opensearch-data"


def get_tui_dir() -> Path:
    """Get the TUI directory for TUI-specific files.
    
    Returns:
        Path to tui directory (~/.openrag/tui/ or ./tui/ in containers)
    """
    tui_dir = get_openrag_home() / "tui"
    tui_dir.mkdir(parents=True, exist_ok=True)
    return tui_dir


def get_tui_env_file() -> Path:
    """Get the TUI .env file path.
    
    Returns:
        Path to .env file
    """
    return get_tui_dir() / ".env"


def get_tui_compose_file(gpu: bool = False) -> Path:
    """Get the TUI docker-compose file path.
    
    Args:
        gpu: If True, returns path to docker-compose.gpu.yml
    
    Returns:
        Path to docker-compose file
    """
    filename = "docker-compose.gpu.yml" if gpu else "docker-compose.yml"
    return get_tui_dir() / filename


# Backward compatibility functions for migration
def get_legacy_paths() -> dict:
    """Get legacy (old) paths for migration purposes.
    
    Returns:
        Dictionary mapping resource names to their old paths
    """
    cwd = Path.cwd()
    return {
        "config": cwd / "config" / "config.yaml",
        "keys_dir": cwd / "keys",
        "private_key": cwd / "keys" / "private_key.pem",
        "public_key": cwd / "keys" / "public_key.pem",
        "documents": cwd / "openrag-documents",
        "flows": cwd / "flows",
        "tui_env": cwd / ".env",
        "tui_compose": cwd / "docker-compose.yml",
        "tui_compose_gpu": cwd / "docker-compose.gpu.yml",
        "opensearch_data": cwd / "opensearch-data",
    }
