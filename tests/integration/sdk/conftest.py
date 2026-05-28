"""
Shared fixtures and setup for OpenRAG SDK integration tests.

All tests in this directory require a running OpenRAG instance.
Set OPENRAG_URL (default: http://localhost:3000) before running.
"""

import os
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

_cached_api_key: str | None = None
_base_url = os.environ.get("OPENRAG_URL", "http://localhost:3000")
_onboarding_done = False


@pytest_asyncio.fixture(scope="session", autouse=True)
async def ensure_onboarding():
    """Ensure the OpenRAG instance is onboarded before running tests.

    Uses httpx.AsyncClient so the async event loop is never blocked,
    even on a slow or unreachable server.
    """
    global _onboarding_done
    if _onboarding_done:
        return

    onboarding_payload = {
        "llm_provider": "openai",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "llm_model": "gpt-4o-mini",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as ac:
            response = await ac.post(
                f"{_base_url}/api/onboarding",
                json=onboarding_payload,
            )
        if response.status_code in (200, 204):
            print("[SDK Tests] Onboarding completed successfully")
        else:
            print(f"[SDK Tests] Onboarding returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"[SDK Tests] Onboarding request failed: {e}")

    _onboarding_done = True


async def _fetch_api_key() -> str:
    """Fetch or create a test API key from the running instance (async, cached)."""
    global _cached_api_key
    if _cached_api_key is not None:
        return _cached_api_key

    async with httpx.AsyncClient(timeout=30.0) as ac:
        response = await ac.post(
            f"{_base_url}/api/keys",
            json={"name": "SDK Integration Test"},
        )

    if response.status_code == 401:
        pytest.skip("Cannot create API key — authentication required")

    assert response.status_code == 200, f"Failed to create API key: {response.text}"
    _cached_api_key = response.json()["api_key"]
    return _cached_api_key


@pytest_asyncio.fixture
async def client():
    """OpenRAG client authenticated with a valid test API key."""
    from openrag_sdk import OpenRAGClient

    api_key = await _fetch_api_key()
    # The SDK defaults to a 30s timeout for *all* requests. Streaming chat on a
    # cold CI box (model spin-up + flow init before the first byte) routinely
    # exceeds that, surfacing as httpx.ReadTimeout. Use a generous timeout here.
    c = OpenRAGClient(api_key=api_key, base_url=_base_url, timeout=120.0)
    yield c
    await c.close()


@pytest.fixture
def base_url() -> str:
    """The base URL of the running OpenRAG instance."""
    return _base_url


@pytest.fixture
def test_file(tmp_path) -> Path:
    """A uniquely-named markdown file ready for ingestion."""
    file_path = tmp_path / f"sdk_test_doc_{uuid.uuid4().hex[:8]}.md"
    file_path.write_text(
        f"# SDK Integration Test Document\n\n"
        f"ID: {uuid.uuid4()}\n\n"
        "This document tests the OpenRAG Python SDK.\n\n"
        "It contains unique content about purple elephants dancing.\n"
    )
    return file_path
