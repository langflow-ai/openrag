from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import api.connectors as connectors_api
import api.documents as documents_api
from connectors.langflow_connector_service import LangflowConnectorService
from models.processors import LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from models.url import LangflowUrlProcessor
from session_manager import User


@pytest.mark.asyncio
async def test_check_filename_exists_queries_active_backend(monkeypatch):
    backend = Mock()
    backend.filename_exists = AsyncMock(return_value=True)

    monkeypatch.setattr(
        documents_api,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    response = await documents_api.check_filename_exists(
        filename="example.pdf",
        session_manager=Mock(),
        user=User(user_id="u1", email="u1@example.com", name="User One"),
    )

    assert response.status_code == 200
    assert response.body == b'{"exists":true,"filename":"example.pdf"}'
    args = backend.filename_exists.await_args.args
    assert args[0] == "example.pdf"
    assert args[1].user_id == "u1"
    assert args[1].user_email == "u1@example.com"


@pytest.mark.asyncio
async def test_delete_documents_by_filename_uses_active_backend(monkeypatch):
    backend = Mock()
    backend.delete_by_filename = AsyncMock(return_value=4)

    monkeypatch.setattr(
        documents_api,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    payload, status_code = await documents_api.delete_documents_by_filename_core(
        filename="example.pdf",
        session_manager=Mock(),
        user_id="u1",
        jwt_token="Bearer test-token",
        user_email="u1@example.com",
    )

    assert status_code == 200
    assert payload["success"] is True
    assert payload["deleted_chunks"] == 4
    args = backend.delete_by_filename.await_args.args
    assert args[0] == "example.pdf"
    assert args[1].user_id == "u1"
    assert args[1].user_email == "u1@example.com"


@pytest.mark.asyncio
async def test_langflow_file_processor_replaces_duplicate_in_active_backend(monkeypatch, tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello", encoding="utf-8")

    session_manager = Mock()
    langflow_file_service = Mock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(return_value={"ok": True})
    backend = Mock()
    backend.filename_exists = AsyncMock(return_value=True)
    backend.delete_by_filename = AsyncMock(return_value=2)

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="u1",
        owner_email="u1@example.com",
        jwt_token="Bearer test-token",
        replace_duplicates=True,
    )

    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={str(file_path): FileTask(file_path=str(file_path), filename="report.txt")},
    )
    file_task = upload_task.file_tasks[str(file_path)]

    await processor.process_item(upload_task, str(file_path), file_task)

    exists_args = backend.filename_exists.await_args.args
    assert exists_args[0] == "report.txt"
    assert exists_args[1].user_id == "u1"
    assert exists_args[1].user_email == "u1@example.com"
    backend.delete_by_filename.assert_awaited_once()
    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
    langflow_file_service.upload_and_ingest_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_synced_file_ids_for_connector_uses_active_backend(monkeypatch):
    backend = Mock()
    backend.list_connector_file_refs = AsyncMock(
        return_value=(["doc-1"], ["report.pdf"])
    )

    monkeypatch.setattr(
        connectors_api,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    file_ids, filenames = await connectors_api.get_synced_file_ids_for_connector(
        connector_type="google_drive",
        user_id="u1",
        user_email="u1@example.com",
        session_manager=Mock(),
        jwt_token="Bearer test-token",
    )

    assert file_ids == ["doc-1"]
    assert filenames == ["report.pdf"]
    args = backend.list_connector_file_refs.await_args.args
    assert args[0] == "google_drive"
    assert args[1].user_id == "u1"
    assert args[1].user_email == "u1@example.com"


@pytest.mark.asyncio
async def test_langflow_connector_service_uses_backend_delete_before_reingest(monkeypatch):
    langflow_service = Mock()
    langflow_service.upload_user_file = AsyncMock(
        return_value={"id": "lf-1", "path": "/tmp/report.pdf"}
    )
    langflow_service.delete_user_file = AsyncMock()
    langflow_service.run_ingestion_flow = AsyncMock(return_value={"ok": True})
    session_manager = Mock()
    backend = Mock()
    backend.delete_by_document_id = AsyncMock(return_value=3)
    backend.delete_by_filename = AsyncMock(return_value=0)

    service = LangflowConnectorService(session_manager=session_manager)
    service.langflow_service = langflow_service

    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    document = SimpleNamespace(
        id="doc-1",
        filename="report.pdf",
        mimetype="application/pdf",
        content=b"hello",
        source_url="https://example.com/report.pdf",
        acl=None,
    )

    result = await service.process_connector_document(
        document=document,
        owner_user_id="u1",
        connector_type="google_drive",
        jwt_token="Bearer test-token",
        owner_name="User One",
        owner_email="u1@example.com",
    )

    assert result["status"] == "indexed"
    backend.delete_by_document_id.assert_awaited_once()
    backend.delete_by_filename.assert_not_called()


@pytest.mark.asyncio
async def test_langflow_url_processor_uses_effective_jwt_without_opensearch_client():
    langflow_file_service = Mock()
    langflow_file_service.run_url_ingestion_flow = AsyncMock(return_value={"ok": True})
    session_manager = Mock()
    session_manager.get_effective_jwt_token.return_value = "anon-jwt"

    processor = LangflowUrlProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        docs_url="https://example.com/docs",
        crawl_depth=1,
        owner_user_id=None,
        owner_email="anonymous@localhost",
        connector_type="openrag_docs",
    )

    upload_task = UploadTask(
        task_id="task-url-1",
        total_files=1,
        file_tasks={
            "https://example.com/docs": FileTask(
                file_path="https://example.com/docs",
                filename="https://example.com/docs",
            )
        },
    )
    file_task = upload_task.file_tasks["https://example.com/docs"]

    await processor.process_item(
        upload_task,
        "https://example.com/docs",
        file_task,
    )

    session_manager.get_effective_jwt_token.assert_called_once_with(None, None)
    assert not session_manager.get_user_opensearch_client.called
    langflow_file_service.run_url_ingestion_flow.assert_awaited_once()
    kwargs = langflow_file_service.run_url_ingestion_flow.await_args.kwargs
    assert kwargs["jwt_token"] == "anon-jwt"
    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
