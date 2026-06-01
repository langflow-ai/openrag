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
os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

# RBAC is OFF by default in production. For tests we keep it ON so the
# RBAC assertions in admin-endpoint and require_permission tests aren't
# silently bypassed. Specific tests that exercise the kill switch
# override this via monkeypatch.
os.environ.setdefault("OPENRAG_RBAC_ENFORCE", "true")

# Pin the RBAC/SQL DB to an isolated temp file BEFORE any code that
# imports `db.engine` runs. The DB engine module reads DATABASE_URL at
# init time, so this must happen at module load. Without it the
# integration tests share `data/openrag.db` with a developer's local
# install (or a stale CI volume), which is both flaky and unsafe.
if not os.environ.get("SDK_TESTS_ONLY") == "true":
    _test_db_dir = tempfile.mkdtemp(prefix="openrag-itest-db-")
    _test_db_path = Path(_test_db_dir) / "openrag.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"

from config.settings import clients  # noqa: E402
from main import generate_jwt_keys  # noqa: E402
from session_manager import SessionManager  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def onboard_system(request):
    """Perform initial onboarding once for all tests in the session.

    This ensures the OpenRAG config is marked as edited and properly initialized
    so that tests can use the /settings endpoint.

    Skips in-process backend setup when SDK_TESTS_ONLY=true (SDK tests talk to
    an already-running external stack and must not wipe its state).
    """
    if os.environ.get("SDK_TESTS_ONLY") == "true":
        yield
        return
    selected_items = getattr(request.session, "items", [])
    if selected_items and all(
        item.get_closest_marker("openrag_skip_app_onboard") for item in selected_items
    ):
        yield
        return

    # Delete any existing config to ensure clean onboarding
    config_file = Path("config/config.yaml")
    if config_file.exists():
        config_file.unlink()

    # Apply Alembic migrations to the test DB BEFORE the FastAPI app is
    # built. The app's @on_event("startup") (which calls init_engine and
    # would normally run schema creation) only fires when uvicorn boots
    # — but integration tests await create_app() directly. Without this
    # explicit migration, the very first RBAC query inside any
    # require_permission-gated endpoint dies with
    # "no such table: permissions".
    from db.migrations_runtime import run_alembic_upgrade_async

    await run_alembic_upgrade_async("head")

    # Bind the SQLAlchemy engine to the migrated DB. init_engine is
    # idempotent and synchronous; safe to call from the test event loop.
    from db.engine import init_engine

    init_engine()

    # Clean up OpenSearch indices to ensure fresh state for tests
    try:
        await clients.initialize()
        await clients.opensearch.indices.delete(index="_all", ignore_unavailable=True)
        print("[DEBUG] Wiped all OpenSearch indices via API")
    except Exception as e:
        print(f"[DEBUG] Could not wipe OpenSearch indices: {e}")

    # Create app and perform onboarding via API
    import httpx

    from main import create_app, startup_tasks

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
            print("[DEBUG] Session onboarding completed successfully")

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
    print(
        f"[DEBUG] SessionManager created with keys: private={sm.private_key_path}, public={sm.public_key_path}"
    )
    return sm


@pytest.fixture
def test_documents_dir():
    """Create a temporary directory with test documents."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_dir = Path(temp_dir)

        # Create some test files in supported formats
        (test_dir / "test1.md").write_text(
            "# Machine Learning Document\n\nThis is a test document about machine learning."
        )
        (test_dir / "test2.md").write_text(
            "# AI Document\n\nAnother document discussing artificial intelligence."
        )
        (test_dir / "test3.md").write_text(
            "# Data Science Document\n\nThis is a markdown file about data science."
        )

        # Create subdirectory with files
        sub_dir = test_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.md").write_text(
            "# Neural Networks\n\nNested document about neural networks."
        )

        yield test_dir


@pytest.fixture
def test_single_file():
    """Create a single test file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix="_test_document.md", delete=False) as f:
        f.write(
            "# Single Test Document\n\nThis is a test document about OpenRAG testing framework. This document contains multiple sentences to ensure proper chunking. The content should be indexed and searchable in OpenSearch after processing."
        )
        temp_path = f.name

    yield temp_path

    # Cleanup
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass
