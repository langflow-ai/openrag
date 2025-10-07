"""
Root conftest.py for pytest configuration and shared fixtures.
This file contains fixtures that are available to all test modules.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest

# Configure environment for testing
os.environ["ENVIRONMENT"] = "test"
os.environ["OPENSEARCH_HOST"] = "localhost"
os.environ["OPENSEARCH_PORT"] = "9200"
os.environ["OPENSEARCH_USER"] = "admin"
os.environ["OPENSEARCH_PASSWORD"] = "admin"
os.environ["JWT_SECRET_KEY"] = "test_secret_key_for_testing_only"
os.environ["LANGFLOW_URL"] = "http://localhost:7860"

# Import fixtures from fixture modules
pytest_plugins = [
    "tests.fixtures.opensearch_fixtures",
    "tests.fixtures.service_fixtures",
    "tests.fixtures.connector_fixtures",
]


@pytest.fixture(scope="session")
def event_loop_policy():
    """Set the event loop policy for the test session."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def event_loop(event_loop_policy):
    """Create an instance of the default event loop for the test session."""
    loop = event_loop_policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_file(temp_dir: Path) -> Path:
    """Create a test file with sample content."""
    test_file = temp_dir / "test_document.txt"
    test_file.write_text("This is a test document for OpenRAG testing.")
    return test_file


@pytest.fixture
def sample_document_data() -> dict:
    """Provide sample document data for testing."""
    return {
        "id": "test_doc_123",
        "filename": "test_document.pdf",
        "content": "Sample document content for testing",
        "metadata": {
            "source": "test",
            "uploaded_by": "test_user",
            "created_at": "2025-01-01T00:00:00Z",
        },
        "embedding": [0.1] * 768,  # Sample embedding vector
    }


@pytest.fixture
def sample_knowledge_filter_data() -> dict:
    """Provide sample knowledge filter data for testing."""
    return {
        "id": "filter_123",
        "name": "Test Filter",
        "description": "A test knowledge filter",
        "query": "test query",
        "document_ids": ["doc1", "doc2", "doc3"],
        "created_by": "test_user",
    }


@pytest.fixture
def sample_user_data() -> dict:
    """Provide sample user data for testing."""
    return {
        "user_id": "test_user_123",
        "email": "test@example.com",
        "name": "Test User",
        "roles": ["user"],
    }


@pytest.fixture
def sample_jwt_token() -> str:
    """Provide a sample JWT token for testing."""
    return "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0X3VzZXJfMTIzIiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwibmFtZSI6IlRlc3QgVXNlciIsInJvbGVzIjpbInVzZXIiXX0.test_signature"


@pytest.fixture
def auth_headers(sample_jwt_token: str) -> dict:
    """Provide authentication headers for testing."""
    return {"Authorization": f"Bearer {sample_jwt_token}"}


@pytest.fixture
def sample_flow_data() -> dict:
    """Provide sample Langflow flow data for testing."""
    return {
        "id": "flow_123",
        "name": "Test Flow",
        "description": "A test flow for OpenRAG",
        "data": {
            "nodes": [
                {
                    "id": "node1",
                    "type": "input",
                    "data": {"label": "Input Node"},
                }
            ],
            "edges": [],
        },
    }


@pytest.fixture
def sample_chat_message() -> dict:
    """Provide sample chat message data for testing."""
    return {
        "session_id": "session_123",
        "message": "What is OpenRAG?",
        "user_id": "test_user_123",
        "timestamp": "2025-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_conversation_data() -> list:
    """Provide sample conversation history for testing."""
    return [
        {
            "role": "user",
            "content": "Hello, what can you help me with?",
            "timestamp": "2025-01-01T00:00:00Z",
        },
        {
            "role": "assistant",
            "content": "I can help you search and understand your documents.",
            "timestamp": "2025-01-01T00:00:01Z",
        },
    ]


@pytest.fixture
def sample_connector_config() -> dict:
    """Provide sample connector configuration for testing."""
    return {
        "connector_type": "google_drive",
        "credentials": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "refresh_token": "test_refresh_token",
        },
        "settings": {
            "folder_id": "test_folder_id",
            "sync_interval": 3600,
        },
    }


@pytest.fixture
def sample_search_query() -> dict:
    """Provide sample search query for testing."""
    return {
        "query": "artificial intelligence and machine learning",
        "filters": {
            "source": "test",
            "date_range": {
                "start": "2025-01-01",
                "end": "2025-12-31",
            },
        },
        "limit": 10,
    }


@pytest.fixture
def sample_embedding_vector() -> list:
    """Provide a sample embedding vector for testing."""
    return [0.1 * i for i in range(768)]


@pytest.fixture
def test_documents_batch() -> list:
    """Provide a batch of test documents for testing."""
    return [
        {
            "id": f"doc_{i}",
            "filename": f"document_{i}.pdf",
            "content": f"This is test document number {i}",
            "metadata": {"index": i, "type": "test"},
        }
        for i in range(10)
    ]


# Environment and configuration fixtures


@pytest.fixture
def test_env_vars() -> dict:
    """Provide test environment variables."""
    return {
        "OPENSEARCH_HOST": "localhost",
        "OPENSEARCH_PORT": "9200",
        "OPENSEARCH_USER": "admin",
        "OPENSEARCH_PASSWORD": "admin",
        "LANGFLOW_URL": "http://localhost:7860",
        "JWT_SECRET_KEY": "test_secret_key",
        "ENVIRONMENT": "test",
    }


@pytest.fixture
def mock_opensearch_response() -> dict:
    """Provide a mock OpenSearch response for testing."""
    return {
        "took": 5,
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "max_score": 1.0,
            "hits": [
                {
                    "_index": "documents",
                    "_id": "test_doc_123",
                    "_score": 1.0,
                    "_source": {
                        "filename": "test_document.pdf",
                        "content": "Sample document content",
                        "metadata": {"source": "test"},
                    },
                }
            ],
        },
    }


@pytest.fixture
def mock_langflow_response() -> dict:
    """Provide a mock Langflow response for testing."""
    return {
        "session_id": "session_123",
        "outputs": [
            {
                "outputs": [
                    {
                        "results": {
                            "message": {
                                "text": "This is a test response from Langflow"
                            }
                        }
                    }
                ]
            }
        ],
    }
