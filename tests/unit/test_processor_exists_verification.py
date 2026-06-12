"""Post-ingestion verification must not fail files on OpenSearch outages.

#1851 added "verify the document actually landed in OpenSearch" checks after
Langflow ingestion. ``check_document_exists`` returns False on persistent
OpenSearch errors ("safer to reprocess than skip") — correct for its dedupe
callers, but the verification callers interpreted that same False as "the
chunks never landed" and marked files FAILED. A transient auth/connectivity
blip (e.g. OpenSearch's lazy JWKS load returning 401s right after startup)
then failed every in-flight file, which is what broke
test_onboarding_sample_docs in CI.

Covers the ``on_error`` mode on ``check_document_exists`` and the
``_verification_client`` selection helper.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import models.processors as processors_module
from models.processors import TaskProcessor, _verification_client


def _failing_client() -> MagicMock:
    client = MagicMock()
    client.search = AsyncMock(
        side_effect=ConnectionError("AuthenticationException(401, 'Unauthorized')")
    )
    return client


def _hit_client(has_hit: bool) -> MagicMock:
    client = MagicMock()
    client.search = AsyncMock(return_value={"hits": {"hits": [{"_id": "x"}] if has_hit else []}})
    return client


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Skip the exponential-backoff sleeps so retry exhaustion is instant.

    Returns the sleep mock so tests can assert on the retry count."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr(processors_module.asyncio, "sleep", sleep_mock)
    return sleep_mock


@pytest.mark.asyncio
async def test_exists_check_error_defaults_to_missing():
    """Dedupe callers keep the historical contract: error -> reprocess."""
    exists = await TaskProcessor().check_document_exists("hash", _failing_client())
    assert exists is False


@pytest.mark.asyncio
async def test_exists_check_error_assume_exists_for_verification():
    """Verification callers must not turn an infra error into a FAILED file."""
    exists = await TaskProcessor().check_document_exists(
        "hash", _failing_client(), on_error="assume_exists"
    )
    assert exists is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("on_error", "expected"),
    [("assume_missing", False), ("assume_exists", True)],
)
async def test_exists_check_exhausts_retries_before_error_fallback(
    _fast_retries, on_error, expected
):
    """Both modes must still exhaust all retries before giving up — the
    error fallback only fires on the final attempt."""
    client = _failing_client()
    exists = await TaskProcessor().check_document_exists("hash", client, on_error=on_error)
    assert exists is expected
    assert client.search.await_count == 3  # all attempts used
    assert _fast_retries.await_count == 2  # 3 attempts -> 2 backoff sleeps


@pytest.mark.asyncio
@pytest.mark.parametrize("on_error", ["assume_missing", "assume_exists"])
@pytest.mark.parametrize("has_hit", [True, False])
async def test_exists_check_mode_irrelevant_when_opensearch_answers(on_error, has_hit):
    exists = await TaskProcessor().check_document_exists(
        "hash", _hit_client(has_hit), on_error=on_error
    )
    assert exists is has_hit


def test_verification_client_prefers_platform_writer(monkeypatch):
    writer = MagicMock()
    monkeypatch.setattr("config.settings.clients.opensearch", writer)
    assert _verification_client(MagicMock()) is writer


def test_verification_client_falls_back_when_writer_missing(monkeypatch):
    monkeypatch.setattr("config.settings.clients.opensearch", None)
    fallback = MagicMock()
    assert _verification_client(fallback) is fallback
