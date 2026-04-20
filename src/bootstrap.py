from pathlib import Path
from dotenv import load_dotenv
from utils.logging_config import get_logger
logger = get_logger(__name__)

# This module is intended to be imported as the first line in entry points
# to ensure environment variables are available to all subsequent imports.

def load_env():
    """Load environment variables from the project root .env file."""
    # .env is located in the project root (one level up from src/)
    logger.info("Application startup span: loading environment variables")
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

# Execute immediately on import
load_env()
