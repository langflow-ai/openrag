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


def _get_git_commit_sha() -> str:
    """Return the current git commit SHA.

    Resolution order:
      1. OPENRAG_GIT_SHA env var (baked in at build time for containers).
      2. `git rev-parse HEAD` in a local checkout (dev fallback).
      3. "unknown" if neither is available.

    The commit SHA is a non-sensitive build identifier, safe to log.
    """
    import os

    env_sha = os.getenv("OPENRAG_GIT_SHA", "").strip()
    if env_sha:
        return env_sha

    try:
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if sha:
                return sha
    except Exception:
        pass

    return "unknown"


def get_git_commit_sha() -> str:
    """Public accessor for the cached git commit SHA."""
    return OPENRAG_GIT_SHA


OPENRAG_GIT_SHA = _get_git_commit_sha()