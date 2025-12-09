"""Migration utilities for moving OpenRAG files to centralized location.

This module handles migration of files from legacy locations (current working directory)
to the new centralized location (~/.openrag/).
"""

import shutil
from pathlib import Path
from typing import Optional, List, Dict
from utils.logging_config import get_logger
from utils.container_utils import detect_container_environment

logger = get_logger(__name__)


def get_migration_marker_file() -> Path:
    """Get the path to the migration marker file.
    
    This file is created after a successful migration to prevent repeated migrations.
    
    Returns:
        Path to migration marker file
    """
    from utils.paths import get_openrag_home
    return get_openrag_home() / ".migrated"


def is_migration_needed() -> bool:
    """Check if migration is needed.
    
    Migration is not needed if:
    - We're in a container environment
    - Migration has already been completed (marker file exists)
    
    Returns:
        True if migration should be performed, False otherwise
    """
    # Don't migrate in container environments
    if detect_container_environment():
        return False
    
    # Check if migration has already been completed
    marker_file = get_migration_marker_file()
    if marker_file.exists():
        return False
    
    # Check if any legacy files exist
    from utils.paths import get_legacy_paths
    legacy_paths = get_legacy_paths()
    
    for name, path in legacy_paths.items():
        if path.exists():
            logger.info(f"Found legacy file/directory: {path}")
            return True
    
    return False


def migrate_directory(src: Path, dst: Path, description: str) -> bool:
    """Migrate a directory from source to destination.
    
    Args:
        src: Source directory path
        dst: Destination directory path
        description: Human-readable description for logging
    
    Returns:
        True if migration was successful or not needed, False otherwise
    """
    if not src.exists():
        logger.debug(f"Source directory does not exist, skipping: {src}")
        return True
    
    if not src.is_dir():
        logger.warning(f"Source is not a directory: {src}")
        return False
    
    try:
        # Ensure parent directory exists
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # If destination already exists, merge contents
        if dst.exists():
            logger.info(f"Destination already exists, merging: {dst}")
            # Copy contents recursively
            for item in src.iterdir():
                src_item = src / item.name
                dst_item = dst / item.name
                
                if src_item.is_dir():
                    if not dst_item.exists():
                        shutil.copytree(src_item, dst_item)
                        logger.debug(f"Copied directory: {src_item} -> {dst_item}")
                else:
                    if not dst_item.exists():
                        shutil.copy2(src_item, dst_item)
                        logger.debug(f"Copied file: {src_item} -> {dst_item}")
        else:
            # Move entire directory
            shutil.move(str(src), str(dst))
            logger.info(f"Migrated {description}: {src} -> {dst}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to migrate {description} from {src} to {dst}: {e}")
        return False


def migrate_file(src: Path, dst: Path, description: str) -> bool:
    """Migrate a file from source to destination.
    
    Args:
        src: Source file path
        dst: Destination file path
        description: Human-readable description for logging
    
    Returns:
        True if migration was successful or not needed, False otherwise
    """
    if not src.exists():
        logger.debug(f"Source file does not exist, skipping: {src}")
        return True
    
    if not src.is_file():
        logger.warning(f"Source is not a file: {src}")
        return False
    
    try:
        # Ensure parent directory exists
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # Only copy if destination doesn't exist
        if dst.exists():
            logger.debug(f"Destination already exists, skipping: {dst}")
            return True
        
        # Copy the file
        shutil.copy2(src, dst)
        logger.info(f"Migrated {description}: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"Failed to migrate {description} from {src} to {dst}: {e}")
        return False


def perform_migration() -> Dict[str, bool]:
    """Perform migration of all OpenRAG files to centralized location.
    
    Returns:
        Dictionary mapping resource names to migration success status
    """
    if not is_migration_needed():
        logger.debug("Migration not needed or already completed")
        return {}
    
    logger.info("Starting migration of OpenRAG files to centralized location")
    
    from utils.paths import (
        get_config_file,
        get_keys_dir,
        get_documents_dir,
        get_flows_dir,
        get_tui_env_file,
        get_tui_compose_file,
        get_opensearch_data_dir,
        get_legacy_paths,
    )
    
    legacy_paths = get_legacy_paths()
    results = {}
    
    # Migrate configuration file
    if legacy_paths["config"].exists():
        results["config"] = migrate_file(
            legacy_paths["config"],
            get_config_file(),
            "configuration file"
        )
    
    # Migrate JWT keys directory
    if legacy_paths["keys_dir"].exists():
        results["keys"] = migrate_directory(
            legacy_paths["keys_dir"],
            get_keys_dir(),
            "JWT keys directory"
        )
    
    # Migrate documents directory
    if legacy_paths["documents"].exists():
        results["documents"] = migrate_directory(
            legacy_paths["documents"],
            get_documents_dir(),
            "documents directory"
        )
    
    # Migrate flows directory
    if legacy_paths["flows"].exists():
        results["flows"] = migrate_directory(
            legacy_paths["flows"],
            get_flows_dir(),
            "flows directory"
        )
    
    # Migrate TUI .env file
    if legacy_paths["tui_env"].exists():
        results["tui_env"] = migrate_file(
            legacy_paths["tui_env"],
            get_tui_env_file(),
            "TUI .env file"
        )
    
    # Migrate docker-compose files
    if legacy_paths["tui_compose"].exists():
        results["tui_compose"] = migrate_file(
            legacy_paths["tui_compose"],
            get_tui_compose_file(gpu=False),
            "docker-compose.yml"
        )
    
    if legacy_paths["tui_compose_gpu"].exists():
        results["tui_compose_gpu"] = migrate_file(
            legacy_paths["tui_compose_gpu"],
            get_tui_compose_file(gpu=True),
            "docker-compose.gpu.yml"
        )
    
    # Note: We don't migrate opensearch-data as it's typically large and managed by Docker
    # Users can manually move it if needed, or specify a custom path via env var
    
    # Create migration marker file
    marker_file = get_migration_marker_file()
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.write_text(f"Migration completed successfully\n")
        logger.info("Migration marker file created")
    except Exception as e:
        logger.warning(f"Failed to create migration marker file: {e}")
    
    # Log summary
    successful = sum(1 for success in results.values() if success)
    total = len(results)
    logger.info(f"Migration completed: {successful}/{total} items migrated successfully")
    
    if successful < total:
        logger.warning("Some migrations failed. Check logs for details.")
    
    return results


def cleanup_legacy_files(dry_run: bool = True) -> List[str]:
    """Clean up legacy files after successful migration.
    
    This function removes the old files from the current working directory after
    confirming they have been successfully migrated.
    
    Args:
        dry_run: If True, only list files that would be removed without actually removing them
    
    Returns:
        List of file paths that were (or would be) removed
    """
    from utils.paths import get_legacy_paths
    
    legacy_paths = get_legacy_paths()
    removed_files = []
    
    for name, path in legacy_paths.items():
        if not path.exists():
            continue
        
        if dry_run:
            logger.info(f"Would remove: {path}")
            removed_files.append(str(path))
        else:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                logger.info(f"Removed legacy file/directory: {path}")
                removed_files.append(str(path))
            except Exception as e:
                logger.error(f"Failed to remove {path}: {e}")
    
    return removed_files
