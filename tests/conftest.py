import asyncio
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Force no-auth mode for testing by setting OAuth credentials to empty strings
# This ensures anonymous JWT tokens are created automatically
os.environ['GOOGLE_OAUTH_CLIENT_ID'] = ''
os.environ['GOOGLE_OAUTH_CLIENT_SECRET'] = ''

from src.config.settings import clients
from src.session_manager import SessionManager
from src.main import generate_jwt_keys


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def opensearch_client():
    """OpenSearch client for testing - requires running OpenSearch."""
    await clients.initialize()
    yield clients.opensearch
    # Cleanup test indices after tests
    try:
        await clients.opensearch.indices.delete(index="test_documents")
    except Exception:
        pass


@pytest.fixture
def session_manager():
    """Session manager for testing."""
    # Generate RSA keys before creating SessionManager
    generate_jwt_keys()
    sm = SessionManager("test-secret-key")
    print(f"[DEBUG] SessionManager created with keys: private={sm.private_key_path}, public={sm.public_key_path}")
    return sm


@pytest.fixture
def test_documents_dir():
    """Create a temporary directory with test documents."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_dir = Path(temp_dir)
        
        # Create some test files in supported formats
        (test_dir / "test1.md").write_text("# Machine Learning Document\n\nThis is a test document about machine learning.")
        (test_dir / "test2.md").write_text("# AI Document\n\nAnother document discussing artificial intelligence.")
        (test_dir / "test3.md").write_text("# Data Science Document\n\nThis is a markdown file about data science.")
        
        # Create subdirectory with files
        sub_dir = test_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.md").write_text("# Neural Networks\n\nNested document about neural networks.")
        
        yield test_dir


@pytest.fixture
def test_single_file():
    """Create a single test file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='_test_document.md', delete=False) as f:
        f.write("# Single Test Document\n\nThis is a test document about OpenRAG testing framework. This document contains multiple sentences to ensure proper chunking. The content should be indexed and searchable in OpenSearch after processing.")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass