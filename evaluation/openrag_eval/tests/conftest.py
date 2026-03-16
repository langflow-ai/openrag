"""Shared pytest fixtures for openrag_eval tests.

This file contains fixtures that can be used across all test modules.
Fixtures defined here are automatically discovered by pytest.
"""

import logging

import pytest

from openrag_eval.logging_config import ShortNameFormatter
from openrag_eval.utils import load_env_file


@pytest.fixture(scope="session", autouse=True)
def load_environment():
    """Load environment variables from .env file for all tests."""
    load_env_file()
    yield


@pytest.fixture(scope="session", autouse=True)
def configure_logging():
    """Configure logging to match init_logger() format for all tests."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        ShortNameFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    # Get root logger and configure it
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    yield

    # Cleanup after tests
    root_logger.handlers.clear()
