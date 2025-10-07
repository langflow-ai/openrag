"""
Application-level fixtures for testing FastAPI/Starlette endpoints.
"""

import pytest
from starlette.testclient import TestClient
from typing import Generator
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """
    Provide a test client for the Starlette application.
    This allows testing HTTP endpoints without running the server.
    """
    from main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def authenticated_client(test_client: TestClient, sample_jwt_token: str) -> TestClient:
    """
    Provide an authenticated test client with JWT token set.
    """
    test_client.headers = {
        **test_client.headers,
        "Authorization": f"Bearer {sample_jwt_token}",
    }
    return test_client


@pytest.fixture
def admin_jwt_token() -> str:
    """Provide a sample admin JWT token for testing."""
    return "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbl91c2VyIiwiZW1haWwiOiJhZG1pbkBleGFtcGxlLmNvbSIsIm5hbWUiOiJBZG1pbiBVc2VyIiwicm9sZXMiOlsiYWRtaW4iXX0.admin_signature"


@pytest.fixture
def admin_client(test_client: TestClient, admin_jwt_token: str) -> TestClient:
    """Provide an authenticated admin test client."""
    test_client.headers = {
        **test_client.headers,
        "Authorization": f"Bearer {admin_jwt_token}",
    }
    return test_client
