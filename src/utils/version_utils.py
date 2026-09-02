from utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_bomarag_version() -> str:
    """Get BomaRAG version from package metadata."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            for dist_name in ["bomarag", "bomarag-nightly"]:
                try:
                    return version(dist_name)
                except PackageNotFoundError:
                    continue
            raise PackageNotFoundError("bomarag")
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
        logger.warning(f"Failed to get BomaRAG version: {e}")
        return "unknown"


BOMARAG_VERSION = _get_bomarag_version()
