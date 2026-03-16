"""Utility functions for openrag_eval."""

from pathlib import Path

from dotenv import load_dotenv


def load_env_file() -> None:
    """
    Load environment variables from .env file in openrag_evaluation directory.

    This function locates the .env file relative to the package structure and
    loads it using python-dotenv. It can be used by both application code and tests.
    """
    # Navigate up from utils.py location to find .env
    # utils.py is in openrag/evaluation/openrag_eval/src/openrag_eval/utils.py
    # .env is in openrag/evaluation/openrag_eval/.env
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, verbose=True)
