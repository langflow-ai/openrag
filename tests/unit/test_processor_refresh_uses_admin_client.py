"""Index refresh after a duplicate-replace must run on the admin client.

`indices:admin/refresh` is index-wide and cannot be DLS-scoped, so the
read-only `openrag_user_role` does not grant it. The visibility check and the
delete are still issued as the user (delete mutates via the admin client
internally), but the trailing refresh must run under the admin/service client
(`clients.opensearch`) — otherwise OpenSearch returns a 403
`security_exception` for `[indices:admin/refresh] ... backend_roles=[openrag_user]`
during the onboarding "replace duplicate" path.

Regression guard for both processors that issue this refresh:
`DocumentFileProcessor` and `LangflowFileProcessor`.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import DocumentFileProcessor, LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask


def _admin_clients(monkeypatch):
    """Patch the module-level `clients` with a mock admin OpenSearch client."""
    admin_client = AsyncMock()
    admin_client.indices = AsyncMock()
    monkeypatch.setattr(
        "models.processors.clients",
        SimpleNamespace(opensearch=admin_client),
    )
    return admin_client


@pytest.mark.asyncio
async def test_document_processor_refresh_uses_admin_client(monkeypatch, tmp_path):
    admin_client = _admin_clients(monkeypatch)

    user_client = AsyncMock()
    user_client.indices = AsyncMock()
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)

    document_service = MagicMock()
    document_service.docling_service = MagicMock()
    document_service.session_manager = session_manager

    processor = DocumentFileProcessor(
        document_service=document_service,
        models_service=MagicMock(),
        owner_user_id="user-1",
        jwt_token="Bearer user-token",
        replace_duplicates=True,
        session_manager=session_manager,
    )
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()
    processor.process_document_standard = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )

    item = tmp_path / "report.pdf"
    item.write_bytes(b"%PDF-1.4 dummy")
    file_task = FileTask(file_path=str(item))
    file_task.filename = "My Report.pdf"
    upload_task = UploadTask(task_id="task-1", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    # Refresh ran on the admin client, never on the DLS-scoped user client.
    admin_client.indices.refresh.assert_awaited_once()
    user_client.indices.refresh.assert_not_awaited()
    # The visibility check and delete still run as the user.
    processor.check_filename_exists.assert_awaited_once()
    processor.delete_document_by_filename.assert_awaited_once()


@pytest.mark.asyncio
async def test_langflow_processor_refresh_uses_admin_client(monkeypatch, tmp_path):
    admin_client = _admin_clients(monkeypatch)

    user_client = AsyncMock()
    user_client.indices = AsyncMock()
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)

    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="user-1",
        jwt_token="Bearer user-token",
        replace_duplicates=True,
    )
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()

    # The Langflow path reads the file off disk after the refresh.
    item = tmp_path / "report.pdf"
    item.write_bytes(b"%PDF-1.4 dummy")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "My Report.pdf"
    upload_task = UploadTask(task_id="task-1", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    assert file_task.status == TaskStatus.COMPLETED
    admin_client.indices.refresh.assert_awaited_once()
    user_client.indices.refresh.assert_not_awaited()
    processor.delete_document_by_filename.assert_awaited_once()
    langflow_file_service.upload_and_ingest_file.assert_awaited_once()
