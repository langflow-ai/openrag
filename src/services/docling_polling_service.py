"""Backend-side Docling polling coordinator.

Owns the wait loop that previously lived inside the Langflow ingestion flow's
DoclingRemote component. Keeping the loop here means a Langflow execution slot
is held only for the brief chunk/embed/index phase, not for the entire Docling
conversion (which can be many minutes for large or OCR-heavy documents).
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from services.docling_service import (
    DoclingService,
    DoclingStatusSnapshot,
    DoclingTaskState,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)


class PollOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"
    TIMEOUT = "timeout"


@dataclass
class DoclingPollResult:
    outcome: PollOutcome
    detail: Optional[str] = None
    last_snapshot: Optional[DoclingStatusSnapshot] = None
    elapsed_seconds: float = 0.0


class DoclingPollingService:
    """Polls a Docling task to terminal state without involving Langflow."""

    def __init__(self, docling_service: DoclingService):
        self.docling_service = docling_service

    async def poll_until_ready(
        self,
        task_id: str,
        poll_interval: float,
        max_seconds: float,
        max_interval: float = 30.0,
        backoff_factor: float = 1.5,
        transient_retry_budget: int = 5,
    ) -> DoclingPollResult:
        """Loop on Docling status until terminal or until max_seconds elapses.

        Transient errors (network, 5xx, NOT_FOUND seen briefly before the task
        is registered server-side) are absorbed up to ``transient_retry_budget``
        before being surfaced as failures. The interval grows by
        ``backoff_factor`` after each non-success poll, capped at
        ``max_interval``, so we don't hammer Docling for slow conversions.
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")
        if max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")

        start = time.monotonic()
        deadline = start + max_seconds
        interval = poll_interval
        consecutive_not_found = 0
        last_snapshot: Optional[DoclingStatusSnapshot] = None

        logger.debug("Starting Docling polling", task_id=task_id)

        while True:
            logger.debug("Docling polling", task_id=task_id)
            snapshot = await self.docling_service.check_task_status(task_id)
            last_snapshot = snapshot
            logger.debug("Snapshot received", task_id=task_id, snapshot=last_snapshot)
            elapsed = time.monotonic() - start

            if snapshot.state == DoclingTaskState.SUCCESS:
                logger.debug(
                    "Docling task reached SUCCESS",
                    task_id=task_id,
                    elapsed_seconds=round(elapsed, 2),
                )
                return DoclingPollResult(
                    outcome=PollOutcome.SUCCESS,
                    last_snapshot=snapshot,
                    elapsed_seconds=elapsed,
                )

            if snapshot.state == DoclingTaskState.FAILED:
                logger.warning(
                    "Docling task reported FAILED",
                    task_id=task_id,
                    detail=snapshot.detail,
                    elapsed_seconds=round(elapsed, 2),
                )
                return DoclingPollResult(
                    outcome=PollOutcome.FAILED,
                    detail=snapshot.detail or "Docling reported failure",
                    last_snapshot=snapshot,
                    elapsed_seconds=elapsed,
                )

            if snapshot.state == DoclingTaskState.NOT_FOUND:
                # NOT_FOUND immediately after submission can be a brief window
                # before the task is visible. Tolerate up to the transient
                # budget; beyond that, treat as expired/unknown.
                consecutive_not_found += 1
                if consecutive_not_found > transient_retry_budget:
                    logger.warning(
                        "Docling task NOT_FOUND past retry budget",
                        task_id=task_id,
                        elapsed_seconds=round(elapsed, 2),
                    )
                    return DoclingPollResult(
                        outcome=PollOutcome.EXPIRED,
                        detail="Docling task not found (expired or unknown task_id)",
                        last_snapshot=snapshot,
                        elapsed_seconds=elapsed,
                    )
            else:
                consecutive_not_found = 0

            # Compute remaining time before deadline; sleep at most that long.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Docling polling exceeded max_seconds",
                    task_id=task_id,
                    max_seconds=max_seconds,
                )
                return DoclingPollResult(
                    outcome=PollOutcome.TIMEOUT,
                    detail=f"Docling polling timed out after {max_seconds}s",
                    last_snapshot=snapshot,
                    elapsed_seconds=time.monotonic() - start,
                )
            await asyncio.sleep(min(interval, remaining))
            interval = min(interval * backoff_factor, max_interval)
