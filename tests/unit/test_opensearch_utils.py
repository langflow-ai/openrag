"""
Tests for utils/opensearch_utils.py
Validates wait_for_opensearch retry logic, backoff behavior, and error handling.
All external dependencies (OpenSearch client, sleep, logging) are fully mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.opensearch_utils import OpenSearchNotReadyError, wait_for_opensearch


def _make_health(status: str) -> dict:
    """Create a mock cluster health response with the given status."""
    return {"status": status}


@pytest.fixture
def mock_opensearch_client():
    """Provide a mocked AsyncOpenSearch client."""
    client = AsyncMock()
    client.cluster = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def no_sleep():
    """Patch asyncio.sleep so tests run instantly."""
    with patch(
        "utils.opensearch_utils.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        yield mock_sleep


# ── Success on first attempt ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_on_first_attempt_green(mock_opensearch_client, no_sleep):
    """Returns immediately when ping succeeds and cluster status is green."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.return_value = _make_health("green")

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=3
    )

    mock_opensearch_client.ping.assert_called_once()
    mock_opensearch_client.cluster.health.assert_called_once()
    no_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_ready_on_first_attempt_yellow(mock_opensearch_client, no_sleep):
    """Returns immediately when ping succeeds and cluster status is yellow."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.return_value = _make_health("yellow")

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=3
    )

    mock_opensearch_client.ping.assert_called_once()
    no_sleep.assert_not_called()


# ── Success after transient failures ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_after_red_status_then_green(mock_opensearch_client, no_sleep):
    """Retries on red cluster status and succeeds when green is returned."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.side_effect = [
        _make_health("red"),
        _make_health("green"),
    ]

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=3
    )

    assert mock_opensearch_client.ping.call_count == 2
    assert mock_opensearch_client.cluster.health.call_count == 2
    assert no_sleep.call_count == 1


@pytest.mark.asyncio
async def test_ready_after_ping_false_then_true(mock_opensearch_client, no_sleep):
    """Retries when ping returns False and succeeds when ping returns True."""
    mock_opensearch_client.ping.side_effect = [False, True]
    mock_opensearch_client.cluster.health.return_value = _make_health("green")

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=3
    )

    assert mock_opensearch_client.ping.call_count == 2
    assert no_sleep.call_count == 1


@pytest.mark.asyncio
async def test_ready_after_exception_then_success(mock_opensearch_client, no_sleep):
    """Retries on connection errors and succeeds when the client responds."""
    mock_opensearch_client.ping.side_effect = [
        ConnectionError("refused"),
        True,
    ]
    mock_opensearch_client.cluster.health.return_value = _make_health("yellow")

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=3
    )

    assert mock_opensearch_client.ping.call_count == 2
    assert no_sleep.call_count == 1


@pytest.mark.asyncio
async def test_ready_after_mixed_failures(mock_opensearch_client, no_sleep):
    """Handles a mix of exceptions, ping=False, and red status before success."""
    mock_opensearch_client.ping.side_effect = [
        ConnectionError("refused"),
        False,
        True,
        True,
    ]
    mock_opensearch_client.cluster.health.side_effect = [
        _make_health("red"),
        _make_health("green"),
    ]

    await wait_for_opensearch(
        opensearch_client=mock_opensearch_client, max_retries=5
    )

    assert mock_opensearch_client.ping.call_count == 4
    assert no_sleep.call_count == 3


# ── Exhausted retries ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_after_all_retries_exhausted_red_status(
    mock_opensearch_client,
):
    """Raises OpenSearchNotReadyError when cluster status is always red."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.return_value = _make_health("red")

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=3
        )

    assert mock_opensearch_client.ping.call_count == 3


@pytest.mark.asyncio
async def test_raises_after_all_retries_exhausted_ping_false(
    mock_opensearch_client,
):
    """Raises OpenSearchNotReadyError when ping always returns False."""
    mock_opensearch_client.ping.return_value = False

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=3
        )

    assert mock_opensearch_client.ping.call_count == 3
    mock_opensearch_client.cluster.health.assert_not_called()


@pytest.mark.asyncio
async def test_raises_after_all_retries_exhausted_exception(
    mock_opensearch_client,
):
    """Raises OpenSearchNotReadyError when every attempt raises an exception."""
    mock_opensearch_client.ping.side_effect = ConnectionError("refused")

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=2
        )

    assert mock_opensearch_client.ping.call_count == 2


@pytest.mark.asyncio
async def test_single_retry_no_sleep_before_raise(mock_opensearch_client, no_sleep):
    """With max_retries=1, fails immediately without sleeping."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.return_value = _make_health("red")

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=1
        )

    mock_opensearch_client.ping.assert_called_once()
    no_sleep.assert_not_called()


# ── Backoff behavior ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_delay_respects_bounds(mock_opensearch_client, no_sleep):
    """Sleep delay stays within [0, max_delay] and never exceeds max_delay."""
    mock_opensearch_client.ping.return_value = False
    base_delay = 2.0
    max_delay = 15.0

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client,
            max_retries=5,
            base_delay=base_delay,
            max_delay=max_delay,
        )

    # 4 sleeps for 5 retries (no sleep after the last attempt)
    assert no_sleep.call_count == 4

    for call in no_sleep.call_args_list:
        delay = call.args[0]
        assert 0 <= delay <= max_delay


@pytest.mark.asyncio
async def test_exponential_backoff_increases(mock_opensearch_client, no_sleep):
    """Backoff upper bound doubles each attempt (before capping at max_delay)."""
    mock_opensearch_client.ping.return_value = False

    with patch(
        "utils.opensearch_utils.random.uniform", side_effect=lambda lo, hi: hi
    ):
        with pytest.raises(OpenSearchNotReadyError):
            await wait_for_opensearch(
                opensearch_client=mock_opensearch_client,
                max_retries=4,
                base_delay=2.0,
                max_delay=100.0,
            )

    # With jitter pinned to the upper bound, delays should be 2, 4, 8
    delays = [call.args[0] for call in no_sleep.call_args_list]
    assert delays == [2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_max_delay_cap(mock_opensearch_client, no_sleep):
    """Delay is capped at max_delay even when exponential growth exceeds it."""
    mock_opensearch_client.ping.return_value = False

    with patch(
        "utils.opensearch_utils.random.uniform", side_effect=lambda lo, hi: hi
    ):
        with pytest.raises(OpenSearchNotReadyError):
            await wait_for_opensearch(
                opensearch_client=mock_opensearch_client,
                max_retries=6,
                base_delay=2.0,
                max_delay=5.0,
            )

    delays = [call.args[0] for call in no_sleep.call_args_list]
    # base_delay * 2^attempt: 2, 4, 5(cap), 5(cap), 5(cap)
    assert delays == [2.0, 4.0, 5.0, 5.0, 5.0]


# ── Edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_parameters(mock_opensearch_client, no_sleep):
    """Works correctly with default parameter values."""
    mock_opensearch_client.ping.return_value = True
    mock_opensearch_client.cluster.health.return_value = _make_health("green")

    await wait_for_opensearch(opensearch_client=mock_opensearch_client)

    mock_opensearch_client.ping.assert_called_once()


@pytest.mark.asyncio
async def test_error_message_content(mock_opensearch_client):
    """OpenSearchNotReadyError contains a meaningful message."""
    mock_opensearch_client.ping.return_value = False

    with pytest.raises(OpenSearchNotReadyError, match="Failed to verify"):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=1
        )


@pytest.mark.asyncio
async def test_health_check_skipped_when_ping_false(mock_opensearch_client, no_sleep):
    """cluster.health() is never called when ping() returns False."""
    mock_opensearch_client.ping.return_value = False

    with pytest.raises(OpenSearchNotReadyError):
        await wait_for_opensearch(
            opensearch_client=mock_opensearch_client, max_retries=2
        )

    mock_opensearch_client.cluster.health.assert_not_called()
