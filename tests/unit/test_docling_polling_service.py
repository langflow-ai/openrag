"""Unit tests for DoclingPollingService.

Verifies the backend-side polling coordinator that replaces Langflow's
in-flow Docling polling. The coordinator's job is to wait for terminal
Docling state without ever invoking Langflow, so that Langflow execution
slots are reserved for chunking / embedding / indexing only.
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.docling_polling_service import (
    DoclingPollingService,
    PollOutcome,
)
from services.docling_service import DoclingStatusSnapshot, DoclingTaskState


def _snap(state: DoclingTaskState, detail: str | None = None) -> DoclingStatusSnapshot:
    return DoclingStatusSnapshot(state=state, detail=detail)


@pytest.fixture
def mock_docling_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def polling_service(mock_docling_service):
    return DoclingPollingService(mock_docling_service)


@pytest.fixture(autouse=True)
def no_sleep():
    with patch(
        "services.docling_polling_service.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        yield mock_sleep


@pytest.mark.asyncio
async def test_returns_success_immediately_when_already_done(polling_service, mock_docling_service):
    mock_docling_service.check_task_status.return_value = _snap(DoclingTaskState.SUCCESS)

    result = await polling_service.poll_until_ready(
        task_id="t1", poll_interval=1.0, max_seconds=10.0
    )

    assert result.outcome == PollOutcome.SUCCESS
    assert mock_docling_service.check_task_status.call_count == 1


@pytest.mark.asyncio
async def test_loops_through_processing_then_success(
    polling_service, mock_docling_service, no_sleep
):
    mock_docling_service.check_task_status.side_effect = [
        _snap(DoclingTaskState.PENDING),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.SUCCESS),
    ]

    result = await polling_service.poll_until_ready(
        task_id="t1", poll_interval=1.0, max_seconds=60.0
    )

    assert result.outcome == PollOutcome.SUCCESS
    assert mock_docling_service.check_task_status.call_count == 4
    assert no_sleep.call_count == 3


@pytest.mark.asyncio
async def test_returns_failed_on_docling_failure(polling_service, mock_docling_service):
    mock_docling_service.check_task_status.return_value = _snap(
        DoclingTaskState.FAILED, detail="conversion error"
    )

    result = await polling_service.poll_until_ready(
        task_id="t1", poll_interval=1.0, max_seconds=10.0
    )

    assert result.outcome == PollOutcome.FAILED
    assert "conversion error" in (result.detail or "")


@pytest.mark.asyncio
async def test_tolerates_brief_not_found_then_succeeds(
    polling_service, mock_docling_service, no_sleep
):
    """NOT_FOUND immediately after submit is a known race; absorb it."""
    mock_docling_service.check_task_status.side_effect = [
        _snap(DoclingTaskState.NOT_FOUND),
        _snap(DoclingTaskState.NOT_FOUND),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.SUCCESS),
    ]

    result = await polling_service.poll_until_ready(
        task_id="t1",
        poll_interval=1.0,
        max_seconds=60.0,
        transient_retry_budget=5,
    )

    assert result.outcome == PollOutcome.SUCCESS


@pytest.mark.asyncio
async def test_returns_expired_when_not_found_exceeds_budget(
    polling_service, mock_docling_service, no_sleep
):
    mock_docling_service.check_task_status.return_value = _snap(DoclingTaskState.NOT_FOUND)

    result = await polling_service.poll_until_ready(
        task_id="t1",
        poll_interval=1.0,
        max_seconds=60.0,
        transient_retry_budget=2,
    )

    assert result.outcome == PollOutcome.EXPIRED
    assert "not found" in (result.detail or "").lower()


@pytest.mark.asyncio
async def test_returns_timeout_when_max_seconds_exceeded(
    polling_service, mock_docling_service, no_sleep
):
    mock_docling_service.check_task_status.return_value = _snap(DoclingTaskState.PROCESSING)

    # Loop counter — break ourselves after enough iterations to simulate
    # crossing the deadline. We achieve this by having the patched
    # asyncio.sleep advance time past the deadline.
    import time

    real_monotonic = time.monotonic
    base = real_monotonic()
    counter = {"n": 0}

    def fake_monotonic():
        counter["n"] += 1
        # First call is "start"; subsequent calls advance fast.
        return base + counter["n"] * 5.0

    with patch("services.docling_polling_service.time.monotonic", fake_monotonic):
        result = await polling_service.poll_until_ready(
            task_id="t1", poll_interval=1.0, max_seconds=2.0
        )

    assert result.outcome == PollOutcome.TIMEOUT


@pytest.mark.asyncio
async def test_invalid_arguments(polling_service):
    with pytest.raises(ValueError):
        await polling_service.poll_until_ready(task_id="t1", poll_interval=0, max_seconds=10)
    with pytest.raises(ValueError):
        await polling_service.poll_until_ready(task_id="t1", poll_interval=1.0, max_seconds=0)


@pytest.mark.asyncio
async def test_backoff_grows_interval_up_to_cap(polling_service, mock_docling_service, no_sleep):
    """Verify the sleep interval grows until it hits max_interval."""
    mock_docling_service.check_task_status.side_effect = [
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.PROCESSING),
        _snap(DoclingTaskState.SUCCESS),
    ]

    await polling_service.poll_until_ready(
        task_id="t1",
        poll_interval=1.0,
        max_seconds=120.0,
        max_interval=4.0,
        backoff_factor=2.0,
    )

    # Sleeps after 4 non-success checks: 1, 2, 4, 4 (capped). Actual sleep
    # call args are min(interval, remaining) — remaining is large, so we
    # see the raw progression.
    sleeps = [call.args[0] for call in no_sleep.call_args_list]
    assert sleeps == [1.0, 2.0, 4.0, 4.0]
