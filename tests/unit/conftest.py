"""Unit test configuration.

Overrides the session-scoped onboard_system fixture from the root conftest
so that unit tests don't require running infrastructure (Langflow, OpenSearch, etc.).
"""

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def onboard_system():
    """No-op override — unit tests mock their own dependencies."""
    yield
