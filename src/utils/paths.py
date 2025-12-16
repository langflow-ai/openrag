"""Host-side path management for OpenRAG TUI.

This module provides functions for TUI to get standardized paths on the host machine.
All TUI files are centralized under ~/.openrag/ to avoid cluttering the user's CWD.

Note: This module is for HOST-SIDE (TUI) use only. Container code should not use these paths.
"""

from pathlib import Path


def get_openrag_home() -> Path:
    """Get the OpenRAG home directory on the host.
    
    Returns:
        Path to ~/.openrag/ directory
    """
    home_dir = Path.home() / ".openrag"
    home_dir.mkdir(parents=True, exist_ok=True)
    return home_dir


def get_tui_dir() -> Path:
    """Get the TUI directory for TUI-specific files.
    
    Returns:
        Path to ~/.openrag/tui/ directory
    """
    tui_dir = get_openrag_home() / "tui"
    tui_dir.mkdir(parents=True, exist_ok=True)
    return tui_dir


def get_tui_env_file() -> Path:
    """Get the TUI .env file path.
    
    Returns:
        Path to ~/.openrag/tui/.env file
    """
    return get_tui_dir() / ".env"


def get_tui_compose_file(gpu: bool = False) -> Path:
    """Get the TUI docker-compose file path.
    
    Args:
        gpu: If True, returns path to docker-compose.gpu.yml
    
    Returns:
        Path to docker-compose file in ~/.openrag/tui/
    """
    filename = "docker-compose.gpu.yml" if gpu else "docker-compose.yml"
    return get_tui_dir() / filename


def get_legacy_paths() -> dict:
    """Get legacy (CWD-based) paths for migration purposes.

    Returns:
        Dictionary mapping resource names to their old CWD-based paths
    """
    cwd = Path.cwd()
    return {
        "tui_env": cwd / ".env",
        "tui_compose": cwd / "docker-compose.yml",
        "tui_compose_gpu": cwd / "docker-compose.gpu.yml",
    }


def expand_path(path: str) -> str:
    """Expand $HOME and ~ in a path string to the actual home directory.

    Args:
        path: Path string that may contain $HOME or ~

    Returns:
        Path string with $HOME and ~ expanded to actual home directory
    """
    if not path:
        return path
    expanded = path.replace("$HOME", str(Path.home()))
    # Also handle ~ at start of path
    if expanded.startswith("~"):
        expanded = str(Path.home()) + expanded[1:]
    return expanded
