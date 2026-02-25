"""
Tests for utils/langflow_utils.py
Validates wait_for_langflow retry logic, backoff behavior, and error handling.
All external dependencies (HTTP client, sleep, logging) are fully mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.langflow_utils import LangflowNotReadyError, wait_for_langflow


def _make_response(status_code: int) -> MagicMock:
    """Create a mock HTTP response with the given status code."""
    resp = MagicMock()
    resp.status_code = status_code
    return resp


@pytest.fixture
def mock_langflow_client():
    """Provide a mocked langflow HTTP client."""
    return AsyncMock()


@pytest.fixture(autouse=True)
def no_sleep():
    """Patch asyncio.sleep so tests run instantly."""
    with patch("utils.langflow_utils.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep


# ── Success on first attempt ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_on_first_attempt(mock_langflow_client, no_sleep):
    """Returns immediately when health check responds 200 on the first try."""
    mock_langflow_client.get.return_value = _make_response(200)

    await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=3)

    mock_langflow_client.get.assert_called_once_with("/health", timeout=5.0)
    no_sleep.assert_not_called()


# ── Success after transient failures ─────────────────────────────────


@pytest.mark.asyncio
async def test_ready_after_non_200_then_200(mock_langflow_client, no_sleep):
    """Retries on non-200 responses and succeeds when 200 is returned."""
    mock_langflow_client.get.side_effect = [
        _make_response(503),
        _make_response(200),
    ]

    await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=3)

    assert mock_langflow_client.get.call_count == 2
    assert no_sleep.call_count == 1


@pytest.mark.asyncio
async def test_ready_after_exception_then_200(mock_langflow_client, no_sleep):
    """Retries on connection errors and succeeds when 200 is returned."""
    mock_langflow_client.get.side_effect = [
        ConnectionError("refused"),
        _make_response(200),
    ]

    await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=3)

    assert mock_langflow_client.get.call_count == 2
    assert no_sleep.call_count == 1


@pytest.mark.asyncio
async def test_ready_after_mixed_failures(mock_langflow_client, no_sleep):
    """Handles a mix of exceptions and non-200 responses before success."""
    mock_langflow_client.get.side_effect = [
        ConnectionError("refused"),
        _make_response(500),
        TimeoutError("timed out"),
        _make_response(200),
    ]

    await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=5)

    assert mock_langflow_client.get.call_count == 4
    assert no_sleep.call_count == 3


# ── Exhausted retries ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_after_all_retries_exhausted_non_200(mock_langflow_client):
    """Raises LangflowNotReadyError when every attempt returns non-200."""
    mock_langflow_client.get.return_value = _make_response(503)

    with pytest.raises(LangflowNotReadyError):
        await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=3)

    assert mock_langflow_client.get.call_count == 3


@pytest.mark.asyncio
async def test_raises_after_all_retries_exhausted_exception(mock_langflow_client):
    """Raises LangflowNotReadyError when every attempt raises an exception."""
    mock_langflow_client.get.side_effect = ConnectionError("refused")

    with pytest.raises(LangflowNotReadyError):
        await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=2)

    assert mock_langflow_client.get.call_count == 2


@pytest.mark.asyncio
async def test_single_retry_no_sleep_before_raise(mock_langflow_client, no_sleep):
    """With max_retries=1, fails immediately without sleeping."""
    mock_langflow_client.get.return_value = _make_response(500)

    with pytest.raises(LangflowNotReadyError):
        await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=1)

    mock_langflow_client.get.assert_called_once()
    no_sleep.assert_not_called()


# ── Backoff behavior ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_delay_respects_bounds(mock_langflow_client, no_sleep):
    """Sleep delay stays within [delay/2, delay] and never exceeds max_delay."""
    mock_langflow_client.get.return_value = _make_response(503)
    base_delay = 1.0
    max_delay = 4.0

    with pytest.raises(LangflowNotReadyError):
        await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=5, base_delay=base_delay, max_delay=max_delay)

    # 4 sleeps for 5 retries (no sleep after the last attempt)
    assert no_sleep.call_count == 4

    for call in no_sleep.call_args_list:
        delay = call.args[0]
        assert 0 <= delay <= max_delay


@pytest.mark.asyncio
async def test_exponential_backoff_increases(mock_langflow_client, no_sleep):
    """Backoff upper bound doubles each attempt (before capping at max_delay)."""
    mock_langflow_client.get.return_value = _make_response(503)

    with patch("utils.langflow_utils.random.uniform", side_effect=lambda lo, hi: hi):
        with pytest.raises(LangflowNotReadyError):
            await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=4, base_delay=1.0, max_delay=100.0)

    # With jitter pinned to the upper bound, delays should be 1, 2, 4
    delays = [call.args[0] for call in no_sleep.call_args_list]
    assert delays == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_max_delay_cap(mock_langflow_client, no_sleep):
    """Delay is capped at max_delay even when exponential growth exceeds it."""
    mock_langflow_client.get.return_value = _make_response(503)

    with patch("utils.langflow_utils.random.uniform", side_effect=lambda lo, hi: hi):
        with pytest.raises(LangflowNotReadyError):
            await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=6, base_delay=2.0, max_delay=5.0)

    delays = [call.args[0] for call in no_sleep.call_args_list]
    # base_delay * 2^attempt: 2, 4, 5(cap), 5(cap), 5(cap)
    assert delays == [2.0, 4.0, 5.0, 5.0, 5.0]


# ── Edge cases ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_parameters(mock_langflow_client, no_sleep):
    """Works correctly with default parameter values."""
    mock_langflow_client.get.return_value = _make_response(200)

    await wait_for_langflow(langflow_http_client=mock_langflow_client)

    mock_langflow_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_error_message_content(mock_langflow_client):
    """LangflowNotReadyError contains a meaningful message."""
    mock_langflow_client.get.return_value = _make_response(503)

    with pytest.raises(LangflowNotReadyError, match="Failed to verify"):
        await wait_for_langflow(langflow_http_client=mock_langflow_client, max_retries=1)
