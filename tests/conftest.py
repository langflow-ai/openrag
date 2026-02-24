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

from config.settings import clients
from session_manager import SessionManager
from main import generate_jwt_keys


@pytest_asyncio.fixture(scope="session", autouse=True)
async def onboard_system():
    """Perform initial onboarding once for all tests in the session.

    This ensures the OpenRAG config is marked as edited and properly initialized
    so that tests can use the /settings endpoint.
    """
    from pathlib import Path
    import shutil

    # Delete any existing config to ensure clean onboarding
    config_file = Path("config/config.yaml")
    if config_file.exists():
        config_file.unlink()
    
    # Clean up OpenSearch data directory to ensure fresh state for tests
    opensearch_data_path = Path(os.getenv("OPENSEARCH_DATA_PATH", "./opensearch-data"))
    if opensearch_data_path.exists():
        try:
            shutil.rmtree(opensearch_data_path)
            print(f"[DEBUG] Cleaned up OpenSearch data directory: {opensearch_data_path}")
        except Exception as e:
            print(f"[DEBUG] Could not clean OpenSearch data directory: {e}")

    # Initialize clients
    await clients.initialize()

    # Create app and perform onboarding via API
    from main import create_app, startup_tasks
    import httpx

    app = await create_app()
    await startup_tasks(app.state.services)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        onboarding_payload = {
            "llm_provider": "openai",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "llm_model": "gpt-4o-mini",
        }
        resp = await client.post("/onboarding", json=onboarding_payload)
        if resp.status_code not in (200, 204):
            # If it fails, it might already be onboarded, which is fine
            print(f"[DEBUG] Onboarding returned {resp.status_code}: {resp.text}")
        else:
            print(f"[DEBUG] Session onboarding completed successfully")

    yield

    # Cleanup after all tests
    try:
        await clients.close()
    except Exception:
        pass


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