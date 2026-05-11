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
    langflow_service, file_tuple
):
    """Backward compatibility: when no polling service is provided, Langflow
    is invoked immediately after Docling submission (Langflow handles polling).
    """
    result = await langflow_service.upload_and_ingest_file(
        file_tuple=file_tuple,
        docling_polling_service=None,
        file_task=None,
    )

    assert langflow_service.run_ingestion_flow.call_count == 1
    kwargs = langflow_service.run_ingestion_flow.call_args.kwargs
    assert kwargs["docling_task_id"] == "task-abc-123"
    assert result["status"] == "success"


def test_processor_skips_polling_service_when_flag_off(monkeypatch):
    """When ENABLE_BACKEND_DOCLING_POLLING is false, the processor must not
    auto-construct a polling service — legacy single-call path is preserved.
    """
    import config.settings as settings_module
    from models.processors import LangflowFileProcessor

    monkeypatch.setattr(settings_module, "ENABLE_BACKEND_DOCLING_POLLING", False)

    lf_svc = LangflowFileService(docling_service=AsyncMock())
    processor = LangflowFileProcessor(
        langflow_file_service=lf_svc,
        session_manager=None,
    )
    assert processor.docling_polling_service is None


def test_processor_constructs_polling_service_when_flag_on(monkeypatch):
    import config.settings as settings_module
    from models.processors import LangflowFileProcessor
    from services.docling_polling_service import DoclingPollingService

    monkeypatch.setattr(settings_module, "ENABLE_BACKEND_DOCLING_POLLING", True)

    lf_svc = LangflowFileService(docling_service=AsyncMock())
    processor = LangflowFileProcessor(
        langflow_file_service=lf_svc,
        session_manager=None,
    )
    assert isinstance(processor.docling_polling_service, DoclingPollingService)


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
