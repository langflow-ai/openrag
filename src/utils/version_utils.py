from utils.logging_config import get_logger

logger = get_logger(__name__)

def _get_openrag_version() -> str:
    """Get OpenRAG version from package metadata."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        
        try:
            for dist_name in ["openrag", "openrag-nightly"]:
                try:
                    return version(dist_name)
                except PackageNotFoundError:
                    continue
            raise PackageNotFoundError("openrag")
        except PackageNotFoundError:
            # Fallback: try to read from pyproject.toml if package not installed (dev mode)
            try:
                import tomllib
                from pathlib import Path
                
                # Try to find pyproject.toml relative to this file
                current_file = Path(__file__)
                project_root = current_file.parent.parent.parent.parent
                pyproject_path = project_root / "pyproject.toml"
                
                if pyproject_path.exists():
                    with open(pyproject_path, "rb") as f:
                        data = tomllib.load(f)
                        return data.get("project", {}).get("version", "dev")
            except Exception:
                pass
            
            return "dev"
    except Exception as e:
        logger.warning(f"Failed to get OpenRAG version: {e}")
        return "unknown"

OPENRAG_VERSION = _get_openrag_version()