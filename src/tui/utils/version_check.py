"""Version checking utilities for OpenRAG TUI."""

from typing import Optional, Tuple
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def get_latest_docker_version(image_name: str = "langflowai/openrag-backend") -> Optional[str]:
    """
    Get the latest version tag from Docker Hub for OpenRAG containers.
    
    Args:
        image_name: Name of the Docker image to check (default: "langflowai/openrag-backend")
        
    Returns:
        Latest version string if found, None otherwise
    """
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Docker Hub API v2 endpoint for tags
            url = f"https://hub.docker.com/v2/repositories/{image_name}/tags/"
            params = {"page_size": 100, "ordering": "-last_updated"}
            
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                tags = data.get("results", [])
                
                # Filter out non-version tags and find the latest version
                version_tags = []
                for tag in tags:
                    tag_name = tag.get("name", "")
                    # Skip architecture-specific tags (amd64, arm64) and "latest"
                    if tag_name in ["latest", "amd64", "arm64"]:
                        continue
                    # Skip tags that don't look like version numbers
                    # Version format: X.Y.Z (e.g., 0.1.47)
                    # Check if it starts with a digit and contains only digits, dots, and hyphens
                    if tag_name and tag_name[0].isdigit():
                        # Remove dots and hyphens, check if rest is digits
                        cleaned = tag_name.replace(".", "").replace("-", "")
                        if cleaned.isdigit():
                            version_tags.append(tag_name)
                
                if not version_tags:
                    return None
                
                # Sort versions properly and return the latest
                # Use a tuple-based sort key for proper version comparison
                def version_sort_key(v: str) -> tuple:
                    """Convert version string to tuple for sorting."""
                    try:
                        parts = []
                        for part in v.split('.'):
                            # Extract numeric part
                            numeric_part = ''
                            for char in part:
                                if char.isdigit():
                                    numeric_part += char
                                else:
                                    break
                            parts.append(int(numeric_part) if numeric_part else 0)
                        # Pad to at least 3 parts for consistent comparison
                        while len(parts) < 3:
                            parts.append(0)
                        return tuple(parts)
                    except Exception:
                        # Fallback: return tuple of zeros if parsing fails
                        return (0, 0, 0)
                
                version_tags.sort(key=version_sort_key)
                return version_tags[-1]
            else:
                logger.warning(f"Docker Hub API returned status {response.status_code}")
                return None
    except Exception as e:
        logger.debug(f"Error checking Docker Hub for latest version: {e}")
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
    Check if the current version is the latest available on Docker Hub.
    
    Returns:
        Tuple of (is_latest, latest_version, current_version)
    """
    current = get_current_version()
    latest = await get_latest_docker_version()
    
    if latest is None:
        # If we can't check, assume current is latest
        return True, None, current
    
    if current == "unknown":
        # If we can't determine current version, assume it's not latest
        return False, latest, current
    
    comparison = compare_versions(current, latest)
    is_latest = comparison >= 0
    
    return is_latest, latest, current

