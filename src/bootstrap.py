from pathlib import Path
from dotenv import load_dotenv

# This module is intended to be imported as the first line in entry points
# to ensure environment variables and logging are available to all subsequent imports.

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
