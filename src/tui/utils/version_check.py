"""Version checking utilities for OpenRAG TUI."""

import asyncio
from typing import Optional, Tuple
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_latest_pypi_version(package_name: str = "openrag") -> Optional[str]:
    """
    Get the latest version of a package from PyPI.
    
    Args:
        package_name: Name of the package to check (default: "openrag")
        
    Returns:
        Latest version string if found, None otherwise
    """
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"https://pypi.org/pypi/{package_name}/json")
            if response.status_code == 200:
                data = response.json()
                return data.get("info", {}).get("version")
            else:
                logger.warning(f"PyPI API returned status {response.status_code}")
                return None
    except Exception as e:
        logger.debug(f"Error checking PyPI for latest version: {e}")
        return None


def get_current_version() -> str:
    """
    Get the current installed version of OpenRAG.
    
    Returns:
        Version string or "unknown" if not available
    """
    try:
        from importlib.metadata import version
        return version("openrag")
    except Exception:
        try:
            from tui import __version__
            return __version__
        except Exception:
            return "unknown"


def compare_versions(version1: str, version2: str) -> int:
    """
    Compare two version strings.
    
    Args:
        version1: First version string
        version2: Second version string
        
    Returns:
        -1 if version1 < version2, 0 if equal, 1 if version1 > version2
    """
    try:
        # Simple version comparison by splitting on dots and comparing parts
        def normalize_version(v: str) -> list:
            parts = []
            for part in v.split('.'):
                # Split on non-numeric characters and take the first numeric part
                numeric_part = ''
                for char in part:
                    if char.isdigit():
                        numeric_part += char
                    else:
                        break
                parts.append(int(numeric_part) if numeric_part else 0)
            return parts
        
        v1_parts = normalize_version(version1)
        v2_parts = normalize_version(version2)
        
        # Pad shorter version with zeros
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))
        
        for i in range(max_len):
            if v1_parts[i] < v2_parts[i]:
                return -1
            elif v1_parts[i] > v2_parts[i]:
                return 1
        return 0
    except Exception as e:
        logger.debug(f"Error comparing versions: {e}")
        # Fallback: string comparison
        if version1 < version2:
            return -1
        elif version1 > version2:
            return 1
        else:
            return 0


async def check_if_latest() -> Tuple[bool, Optional[str], str]:
    """
    Check if the current version is the latest available on PyPI.
    
    Returns:
        Tuple of (is_latest, latest_version, current_version)
    """
    current = get_current_version()
    latest = await get_latest_pypi_version()
    
    if latest is None:
        # If we can't check, assume current is latest
        return True, None, current
    
    if current == "unknown":
        # If we can't determine current version, assume it's not latest
        return False, latest, current
    
    comparison = compare_versions(current, latest)
    is_latest = comparison >= 0
    
    return is_latest, latest, current

