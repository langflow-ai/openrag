"""Docling usage metering — append-only JSONL record per file submission.

Each record captures the full lifecycle of one Docling conversion attempt:
submission timestamp, terminal outcome, wall-clock elapsed time, file
metadata, and the owner's user id.  Records are written atomically (one
JSON line each) under an asyncio lock so concurrent ingestion tasks never
interleave partial writes.

Deployment mode awareness
--------------------------
When Docling is deployed with Redis Queue (``deployment_mode="rq"``), the
task sits in a queue before a worker picks it up.  The ``elapsed_seconds``
field therefore includes queue wait time in addition to GPU/CPU conversion
time.  The ``deployment_mode`` field in each record lets downstream
billing logic account for this distinction.
"""

import asyncio
import dataclasses
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiofiles

from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class DoclingMeterRecord:
    task_id: str
    filename: str
    size_bytes: int
    mimetype: str
    owner_user_id: Optional[str]
    submitted_at: str  # ISO-8601 UTC timestamp
    terminal_at: str  # ISO-8601 UTC timestamp
    elapsed_seconds: float  # wall-clock from submission to terminal
    outcome: str  # "success" | "failed" | "expired" | "timeout" | "submit_failed"
    failure_detail: Optional[str]
    poll_count: int  # status-check calls made; 0 for legacy (Langflow-polling) path
    deployment_mode: str  # "direct" | "rq"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DoclingMeteringService:
    """Writes one JSONL record per Docling file submission to a log file."""

    def __init__(self, log_path: str, deployment_mode: str = "direct"):
        self._log_path = log_path
        self._deployment_mode = deployment_mode
        self._lock = asyncio.Lock()

    @property
    def deployment_mode(self) -> str:
        return self._deployment_mode

    def build_record(
        self,
        *,
        task_id: str,
        filename: str,
        size_bytes: int,
        mimetype: str,
        owner_user_id: Optional[str],
        submitted_at: str,
        terminal_at: str,
        elapsed_seconds: float,
        outcome: str,
        failure_detail: Optional[str] = None,
        poll_count: int = 0,
    ) -> DoclingMeterRecord:
        return DoclingMeterRecord(
            task_id=task_id,
            filename=filename,
            size_bytes=size_bytes,
            mimetype=mimetype,
            owner_user_id=owner_user_id,
            submitted_at=submitted_at,
            terminal_at=terminal_at,
            elapsed_seconds=round(elapsed_seconds, 3),
            outcome=outcome,
            failure_detail=failure_detail,
            poll_count=poll_count,
            deployment_mode=self._deployment_mode,
        )

    async def record(self, meter_record: DoclingMeterRecord) -> None:
        """Append *meter_record* as a single JSON line to the metering log.

        Errors are swallowed with a warning so a metering failure never
        interrupts the ingestion path.
        """
        line = json.dumps(dataclasses.asdict(meter_record), default=str) + "\n"
        async with self._lock:
            try:
                log_dir = os.path.dirname(os.path.abspath(self._log_path))
                os.makedirs(log_dir, exist_ok=True)
                async with aiofiles.open(self._log_path, "a", encoding="utf-8") as fh:
                    await fh.write(line)
            except Exception as exc:
                logger.warning(
                    "Failed to write Docling meter record",
                    error=str(exc),
                    task_id=meter_record.task_id,
                )
