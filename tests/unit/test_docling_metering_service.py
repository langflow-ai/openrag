"""Unit tests for DoclingMeteringService and its integration with LangflowFileService.

Verifies:
  - JSONL records are written with the correct fields
  - Metering fires on success, polling failure, and Langflow failure
  - Metering is silently skipped when metering_service is None
  - poll_count is forwarded correctly from DoclingPollResult
  - File I/O errors are swallowed (metering never disrupts ingestion)
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.docling_metering_service import DoclingMeteringService, DoclingMeterRecord
from services.docling_polling_service import DoclingPollResult, PollOutcome
from services.langflow_file_service import LangflowFileService
from models.tasks import FileTask


# ── DoclingMeteringService unit tests ────────────────────────────────────────


@pytest.fixture
def metering_service(tmp_path):
    log_file = str(tmp_path / "meter.jsonl")
    return DoclingMeteringService(log_path=log_file, deployment_mode="direct")


def _sample_record(**overrides) -> DoclingMeterRecord:
    defaults = dict(
        task_id="t-001",
        filename="doc.pdf",
        size_bytes=1024,
        mimetype="application/pdf",
        owner_user_id="user-42",
        submitted_at="2026-05-14T12:00:00+00:00",
        terminal_at="2026-05-14T12:00:10+00:00",
        elapsed_seconds=10.0,
        outcome="success",
        failure_detail=None,
        poll_count=3,
        deployment_mode="direct",
    )
    defaults.update(overrides)
    return DoclingMeterRecord(**defaults)


@pytest.mark.asyncio
async def test_record_writes_jsonl_line(metering_service, tmp_path):
    rec = _sample_record()
    await metering_service.record(rec)

    log_path = tmp_path / "meter.jsonl"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["task_id"] == "t-001"
    assert data["outcome"] == "success"
    assert data["poll_count"] == 3
    assert data["deployment_mode"] == "direct"
    assert data["size_bytes"] == 1024


@pytest.mark.asyncio
async def test_record_appends_multiple_lines(metering_service, tmp_path):
    await metering_service.record(_sample_record(task_id="t-001"))
    await metering_service.record(_sample_record(task_id="t-002"))
    await metering_service.record(_sample_record(task_id="t-003"))

    log_path = tmp_path / "meter.jsonl"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3
    ids = [json.loads(l)["task_id"] for l in lines]
    assert ids == ["t-001", "t-002", "t-003"]


@pytest.mark.asyncio
async def test_record_creates_parent_directory(tmp_path):
    nested = str(tmp_path / "a" / "b" / "meter.jsonl")
    svc = DoclingMeteringService(log_path=nested, deployment_mode="rq")
    await svc.record(_sample_record(deployment_mode="rq"))
    assert os.path.isfile(nested)


@pytest.mark.asyncio
async def test_record_swallows_io_errors(metering_service):
    """A file I/O failure must not propagate — metering is fire-and-forget."""
    with patch("aiofiles.open", side_effect=OSError("disk full")):
        # Should not raise.
        await metering_service.record(_sample_record())


def test_build_record_rounds_elapsed(metering_service):
    rec = metering_service.build_record(
        task_id="t-x",
        filename="f.pdf",
        size_bytes=512,
        mimetype="application/pdf",
        owner_user_id=None,
        submitted_at="2026-05-14T00:00:00+00:00",
        terminal_at="2026-05-14T00:00:07+00:00",
        elapsed_seconds=7.123456789,
        outcome="failed",
        failure_detail="OCR crash",
        poll_count=2,
    )
    assert rec.elapsed_seconds == 7.123
    assert rec.deployment_mode == "direct"


# ── Integration tests: LangflowFileService metering wire-up ─────────────────


@pytest.fixture
def file_tuple():
    return ("report.pdf", b"PDF" * 100, "application/pdf")


@pytest.fixture
def file_task():
    return FileTask(file_path="/tmp/report.pdf", filename="report.pdf")


@pytest.fixture
def mock_docling_service():
    svc = AsyncMock()
    svc.upload_to_docling_direct_async.return_value = "task-xyz"
    return svc


@pytest.fixture
def mock_metering_service():
    svc = MagicMock(spec=DoclingMeteringService)
    svc.build_record.return_value = _sample_record()
    svc.record = AsyncMock()
    return svc


@pytest.fixture
def langflow_service(mock_docling_service, mock_metering_service):
    svc = LangflowFileService(
        docling_service=mock_docling_service,
        metering_service=mock_metering_service,
    )
    svc.run_ingestion_flow = AsyncMock(return_value={"status": "ok"})
    return svc


@pytest.mark.asyncio
async def test_metering_called_on_success(
    langflow_service, mock_metering_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.SUCCESS, elapsed_seconds=5.0, poll_count=2
    )
    await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=mock_polling_service,
        file_task=file_task,
    )
    assert mock_metering_service.record.call_count == 1
    build_kwargs = mock_metering_service.build_record.call_args.kwargs
    assert build_kwargs["outcome"] == "success"
    assert build_kwargs["poll_count"] == 2
    assert build_kwargs["size_bytes"] == len(b"PDF" * 100)
    assert build_kwargs["mimetype"] == "application/pdf"


@pytest.mark.asyncio
async def test_metering_called_on_poll_failure(
    langflow_service, mock_metering_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.FAILED, detail="OCR crash", poll_count=5
    )
    with pytest.raises(Exception):
        await langflow_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )
    assert mock_metering_service.record.call_count == 1
    build_kwargs = mock_metering_service.build_record.call_args.kwargs
    assert build_kwargs["outcome"] == "failed"
    assert build_kwargs["failure_detail"] == "OCR crash"
    assert build_kwargs["poll_count"] == 5


@pytest.mark.asyncio
async def test_metering_called_on_langflow_failure(
    langflow_service, mock_metering_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.SUCCESS, elapsed_seconds=3.0, poll_count=1
    )
    langflow_service.run_ingestion_flow = AsyncMock(side_effect=RuntimeError("flow crashed"))

    with pytest.raises(RuntimeError):
        await langflow_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )
    build_kwargs = mock_metering_service.build_record.call_args.kwargs
    assert build_kwargs["outcome"] == "langflow_failed"
    assert "flow crashed" in build_kwargs["failure_detail"]


@pytest.mark.asyncio
async def test_metering_skipped_when_service_is_none(
    mock_docling_service, mock_polling_service, file_tuple, file_task
):
    """When no metering_service is injected, the ingestion still completes normally."""
    svc = LangflowFileService(docling_service=mock_docling_service, metering_service=None)
    svc.run_ingestion_flow = AsyncMock(return_value={"status": "ok"})
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.SUCCESS, elapsed_seconds=1.0, poll_count=1
    )
    result = await svc.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=mock_polling_service,
        file_task=file_task,
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_poll_count_zero_for_legacy_path(
    langflow_service, mock_metering_service, file_tuple, file_task
):
    """Legacy path (no polling service) must record poll_count=0."""
    result = await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=None,
        file_task=file_task,
    )
    assert result["status"] == "success"
    build_kwargs = mock_metering_service.build_record.call_args.kwargs
    assert build_kwargs["poll_count"] == 0
    assert build_kwargs["outcome"] == "success"


@pytest.fixture
def mock_polling_service():
    return AsyncMock()
