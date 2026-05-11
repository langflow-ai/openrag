"""Unit tests for the two-phase Docling + Langflow ingestion flow.

Verifies the core architectural property: when a polling service is provided,
``LangflowFileService.upload_and_ingest_file`` must NOT invoke the Langflow
ingestion flow until Docling reports SUCCESS, and must NEVER invoke it when
Docling fails / expires / times out.
"""

import pytest
from unittest.mock import AsyncMock, patch

from models.tasks import (
    DoclingPhaseStatus,
    FileTask,
    IngestionPhase,
)
from services.docling_polling_service import DoclingPollResult, PollOutcome
from services.langflow_file_service import LangflowFileService


@pytest.fixture
def file_tuple():
    return ("test.pdf", b"PDFDATA", "application/pdf")


@pytest.fixture
def file_task():
    return FileTask(file_path="/tmp/test.pdf", filename="test.pdf")


@pytest.fixture
def mock_docling_service():
    svc = AsyncMock()
    svc.upload_to_docling_direct_async.return_value = "task-abc-123"
    return svc


@pytest.fixture
def mock_polling_service():
    return AsyncMock()


@pytest.fixture
def langflow_service(mock_docling_service):
    svc = LangflowFileService(docling_service=mock_docling_service)
    # Stub the actual Langflow HTTP call — those have their own coverage.
    svc.run_ingestion_flow = AsyncMock(return_value={"status": "ok"})
    return svc


@pytest.mark.asyncio
async def test_two_phase_success_invokes_langflow_with_task_id(
    langflow_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.SUCCESS, elapsed_seconds=2.5
    )

    result = await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=mock_polling_service,
        file_task=file_task,
    )

    # Langflow was invoked exactly once, with the docling_task_id forwarded.
    assert langflow_service.run_ingestion_flow.call_count == 1
    kwargs = langflow_service.run_ingestion_flow.call_args.kwargs
    assert kwargs["docling_task_id"] == "task-abc-123"

    # FileTask reflects full lifecycle.
    assert file_task.docling_task_id == "task-abc-123"
    assert file_task.docling_status == DoclingPhaseStatus.SUCCESS
    assert file_task.phase == IngestionPhase.COMPLETE

    # Result envelope.
    assert result["status"] == "success"
    assert result["docling_task_id"] == "task-abc-123"


@pytest.mark.asyncio
async def test_langflow_not_invoked_on_docling_failure(
    langflow_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.FAILED, detail="OCR engine crashed"
    )

    with pytest.raises(Exception, match="OCR engine crashed"):
        await langflow_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )

    # Crucial assertion — Langflow must never run when Docling failed.
    assert langflow_service.run_ingestion_flow.call_count == 0
    assert file_task.docling_status == DoclingPhaseStatus.FAILED
    # Phase remains DOCLING (never advanced to LANGFLOW).
    assert file_task.phase == IngestionPhase.DOCLING


@pytest.mark.asyncio
async def test_langflow_not_invoked_on_docling_expired(
    langflow_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.EXPIRED, detail="task not found"
    )

    with pytest.raises(Exception, match="expired"):
        await langflow_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )

    assert langflow_service.run_ingestion_flow.call_count == 0
    assert file_task.docling_status == DoclingPhaseStatus.EXPIRED


@pytest.mark.asyncio
async def test_langflow_not_invoked_on_polling_timeout(
    langflow_service, mock_polling_service, file_tuple, file_task
):
    mock_polling_service.poll_until_ready.return_value = DoclingPollResult(
        outcome=PollOutcome.TIMEOUT, detail="exceeded 1800s"
    )

    with pytest.raises(Exception, match="timeout"):
        await langflow_service.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )

    assert langflow_service.run_ingestion_flow.call_count == 0
    assert file_task.docling_status == DoclingPhaseStatus.FAILED


@pytest.mark.asyncio
async def test_phase_progresses_only_after_polling_succeeds(
    langflow_service, mock_polling_service, file_tuple, file_task
):
    """Phase must be DOCLING during polling, then LANGFLOW, then COMPLETE."""
    observed_phases = []

    async def record_then_succeed(*args, **kwargs):
        observed_phases.append(file_task.phase)
        return DoclingPollResult(outcome=PollOutcome.SUCCESS)

    mock_polling_service.poll_until_ready.side_effect = record_then_succeed

    async def record_then_run(*args, **kwargs):
        observed_phases.append(file_task.phase)
        return {"status": "ok"}

    langflow_service.run_ingestion_flow = AsyncMock(side_effect=record_then_run)

    await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=mock_polling_service,
        file_task=file_task,
    )

    assert observed_phases == [IngestionPhase.DOCLING, IngestionPhase.LANGFLOW]
    assert file_task.phase == IngestionPhase.COMPLETE


@pytest.mark.asyncio
async def test_legacy_path_without_polling_service_calls_langflow_directly(
    langflow_service, file_tuple, file_task
):
    """Backward compatibility: when no polling service is provided, Langflow
    is invoked immediately after Docling submission (Langflow handles polling).
    On success the file_task must end with docling_status=SUCCESS so the
    status fields stay coherent — Langflow returning success implies its
    DoclingRemote component consumed the task.
    """
    result = await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=None,
        file_task=file_task,
    )

    assert langflow_service.run_ingestion_flow.call_count == 1
    kwargs = langflow_service.run_ingestion_flow.call_args.kwargs
    assert kwargs["docling_task_id"] == "task-abc-123"
    assert result["status"] == "success"
    # Status fields must not leave the task stuck in PROCESSING.
    assert file_task.docling_status == DoclingPhaseStatus.SUCCESS
    assert file_task.phase == IngestionPhase.COMPLETE
    assert file_task.docling_task_id == "task-abc-123"


def test_processor_default_polling_service_is_none():
    """LangflowFileProcessor no longer constructs a polling service inline.
    The container injects it; absent injection, the processor falls back
    to the legacy single-call path.
    """
    from models.processors import LangflowFileProcessor

    lf_svc = LangflowFileService(docling_service=AsyncMock())
    processor = LangflowFileProcessor(
        langflow_file_service=lf_svc,
        session_manager=None,
    )
    assert processor.docling_polling_service is None


def test_processor_accepts_injected_polling_service():
    """The polling service is passed through unchanged when injected."""
    from models.processors import LangflowFileProcessor

    lf_svc = LangflowFileService(docling_service=AsyncMock())
    injected = AsyncMock()
    processor = LangflowFileProcessor(
        langflow_file_service=lf_svc,
        session_manager=None,
        docling_polling_service=injected,
    )
    assert processor.docling_polling_service is injected


@pytest.mark.asyncio
async def test_task_service_threads_polling_service_to_processor(monkeypatch):
    """TaskService.create_langflow_upload_task must forward its injected
    polling service to the LangflowFileProcessor it constructs. This is the
    DI contract that replaces the processor's inline construction.
    """
    from services.task_service import TaskService

    injected = AsyncMock()
    captured: dict = {}

    class FakeProcessor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("models.processors.LangflowFileProcessor", FakeProcessor)

    async def fake_create_custom_task(*args, **kwargs):
        return "task-id"

    svc = TaskService(docling_polling_service=injected)
    monkeypatch.setattr(svc, "create_custom_task", fake_create_custom_task)

    await svc.create_langflow_upload_task(
        user_id="u1",
        file_paths=["/tmp/x.pdf"],
        langflow_file_service=AsyncMock(),
        session_manager=AsyncMock(),
    )

    assert captured["docling_polling_service"] is injected


@pytest.mark.asyncio
async def test_docling_submit_failure_skips_polling_and_langflow(
    mock_docling_service, mock_polling_service, file_tuple, file_task
):
    mock_docling_service.upload_to_docling_direct_async.side_effect = Exception(
        "docling unreachable"
    )
    svc = LangflowFileService(docling_service=mock_docling_service)
    svc.run_ingestion_flow = AsyncMock()

    with pytest.raises(Exception, match="Docling upload failed"):
        await svc.upload_and_ingest_file(
            file_tuple=file_tuple,
            docling_polling_service=mock_polling_service,
            file_task=file_task,
        )

    assert mock_polling_service.poll_until_ready.call_count == 0
    assert svc.run_ingestion_flow.call_count == 0
    assert file_task.docling_task_id is None
