"""wait_for_opensearch must surface the real failure reason.

Previously the readiness probe gated on ``client.ping()`` (HEAD /), which
opensearchpy implements by swallowing transport/auth/connection errors and
returning ``False`` — collapsing a rejected JWT (401/403), a connection
refusal, and a TLS error into a single uninformative "ping failed" log.

These tests pin the new behaviour: the probe calls ``cluster.health()``
(which raises), the per-attempt warning carries ``status_code``/``info``, and
the final ``OpenSearchNotReadyError`` message embeds the last error.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.opensearch_utils import (  # noqa: E402
    OpenSearchNotReadyError,
    wait_for_opensearch,
)


class _FakeTransportError(Exception):
    """Mimics opensearchpy's TransportError: carries status_code + info."""

    def __init__(self, status_code, error, info):
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.info = info


def _client_with_health(health_side_effect):
    client = MagicMock()
    client.cluster.health = AsyncMock(side_effect=health_side_effect)
    return client


@pytest.mark.asyncio
async def test_ready_when_health_green():
    client = _client_with_health([{"status": "green"}])
    # Should return without raising; no sleeps on first-attempt success.
    await wait_for_opensearch(client, max_retries=1)
    client.cluster.health.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_failure_is_surfaced(monkeypatch):
    err = _FakeTransportError(403, "AuthorizationException", {"reason": "invalid jwt"})
    client = _client_with_health(err)

    captured = []
    monkeypatch.setattr(
        "utils.opensearch_utils.logger.warning",
        lambda msg, **kw: captured.append((msg, kw)),
    )

    with pytest.raises(OpenSearchNotReadyError) as excinfo:
        # tiny delays so the retry loop doesn't actually sleep meaningfully
        await wait_for_opensearch(client, max_retries=2, base_delay=0.0, max_delay=0.0)

    # The real reason must reach the final exception message...
    assert "403" in str(excinfo.value) or "AuthorizationException" in str(excinfo.value)
    # ...and the per-attempt warning must carry structured detail.
    assert captured, "expected at least one readiness-failure warning"
    _, kw = captured[0]
    assert kw["status_code"] == 403
    assert kw["info"] == {"reason": "invalid jwt"}
    assert kw["error_type"] == "_FakeTransportError"


@pytest.mark.asyncio
async def test_connection_error_without_status_code(monkeypatch):
    # A plain ConnectionError-style failure has no status_code attribute.
    client = _client_with_health(ConnectionError("connection refused"))

    captured = []
    monkeypatch.setattr(
        "utils.opensearch_utils.logger.warning",
        lambda msg, **kw: captured.append((msg, kw)),
    )

    with pytest.raises(OpenSearchNotReadyError) as excinfo:
        await wait_for_opensearch(client, max_retries=1, base_delay=0.0, max_delay=0.0)

    assert "connection refused" in str(excinfo.value)
    _, kw = captured[0]
    assert kw["status_code"] is None
    assert kw["error_type"] == "ConnectionError"
