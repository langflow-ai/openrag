import sys
from pathlib import Path

from dotenv import load_dotenv

# This module is intended to be imported as the first line in entry points
# to ensure environment variables and logging are available to all subsequent imports.

# Make the repo root importable so the top-level `enhancements/` package is
# discoverable alongside `src/`. Safe to no-op when the path is already present.
_REPO_ROOT = str(Path(__file__).parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def load_env():
    """Load .env then immediately configure structured logging so all subsequent
    module-level log calls use the correct formatter and processors."""
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    # Configure logging immediately after env vars are available so every
    # subsequent import gets a properly configured logger.
    from utils.logging_config import configure_from_env

    configure_from_env()


# Execute immediately on import
load_env()

from utils.logging_config import get_logger  # noqa: E402 — after configure_from_env

logger = get_logger(__name__)
logger.info("Application startup span: environment loaded")
