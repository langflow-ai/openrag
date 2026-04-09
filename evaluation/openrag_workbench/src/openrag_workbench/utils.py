"""Utility functions for openrag_workbench."""

import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_env_file() -> None:
    """
    Load environment variables from .env file in openrag_workbench directory.

    This function locates the .env file relative to the package structure and
    loads it using python-dotenv. It can be used by both application code and tests.
    """
    
    # Navigate up from utils.py location to find .env
    # utils.py is in openrag/evaluation/openrag_workbench/src/openrag_workbench/utils.py
    # .env is in openrag/evaluation/openrag_workbench/.env
    env_path = Path(__file__).parent.parent.parent / ".env"
    
    if env_path.exists():
        logger.info(f"Loading environment variables from: {env_path}")
        load_dotenv(dotenv_path=env_path)
        logger.info("Environment variables loaded successfully")
    else:
        logger.warning(f".env file not found at: {env_path}")

