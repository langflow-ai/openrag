import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.mark.asyncio
async def test_sync_specific_files_does_not_raise_on_incompatible_type():
    from connectors.service import ConnectorService

    # Instantiate the service
    service = ConnectorService.__new__(ConnectorService)
    service.task_service = MagicMock()
    service.session_manager = MagicMock()
    service.models_service = MagicMock()

    # Mock the connector and config
    connector = MagicMock()
    connector.is_authenticated = True

    # Mock list_files returning an incompatible file (e.g. an .exe)
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "file-1", "name": "document.pdf"},
                {"id": "file-2", "name": "program.exe"},
            ]
        }
    )
    connector.cfg = MagicMock()

    service.get_connector = AsyncMock(return_value=connector)

    # When creating a custom task, we'll return a dummy task ID
    service.task_service.create_custom_task = AsyncMock(return_value="dummy-task-id")

    # Verify that calling sync_specific_files succeeds (no ValueError raised!)
    task_id = await service.sync_specific_files(
        connection_id="conn-id", user_id="user-id", file_ids=["folder-id"], jwt_token="jwt"
    )

    assert task_id == "dummy-task-id"


@pytest.mark.asyncio
async def test_connector_file_processor_fails_incompatible_file():
    from models.processors import ConnectorFileProcessor
    from models.tasks import FileTask, TaskStatus, UploadTask

    connector_service = MagicMock()
    connector = MagicMock()
    connector_service.get_connector = AsyncMock(return_value=connector)
    connection = MagicMock()
    connection.connector_type = "onedrive"
    connector_service.connection_manager.get_connection = AsyncMock(return_value=connection)

    processor = ConnectorFileProcessor(
        connector_service=connector_service,
        connection_id="conn-id",
        files_to_process=[],
        user_id="user-id",
        jwt_token="jwt",
        document_service=MagicMock(),
        models_service=MagicMock(),
    )

    upload_task = UploadTask(task_id="task-id", total_files=1)
    file_task = FileTask(file_path="file-2", filename="program.exe")

    await processor.process_item(upload_task, "file-2", file_task)

    assert file_task.status == TaskStatus.FAILED
    assert "has an incompatible type" in file_task.error
    assert "program.exe" in file_task.error
    assert upload_task.failed_files == 1


@pytest.mark.asyncio
async def test_connector_check_duplicates():
    import json

    from fastapi.responses import JSONResponse

    from api.connectors import ConnectorCheckDuplicatesBody, connector_check_duplicates

    # Mock parameters
    connector_service = MagicMock()
    connection_manager = MagicMock()
    connector_service.connection_manager = connection_manager

    connection = MagicMock()
    connection.connection_id = "conn-id"
    connection.is_active = True
    connection_manager.list_connections = AsyncMock(return_value=[connection])

    connector = MagicMock()
    connector.is_authenticated = True
    connector.authenticate = AsyncMock(return_value=True)

    # Mock folder expansion
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "file-1", "name": "existing.pdf", "mimeType": "application/pdf"},
                {
                    "id": "file-2",
                    "name": "new_file.docx",
                    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                },
            ]
        }
    )
    connector.cfg = MagicMock()
    connector_service.get_connector = AsyncMock(return_value=connector)

    # Mock session_manager and OpenSearch client
    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    # Mock search return value: existing.pdf exists, new_file.docx does not
    opensearch_client.search = AsyncMock(
        return_value={"hits": {"hits": [{"_source": {"filename": "existing.pdf"}}]}}
    )

    user = MagicMock()
    user.user_id = "user-id"
    user.jwt_token = "jwt-token"

    body = ConnectorCheckDuplicatesBody(
        connection_id="conn-id",
        selected_files=[{"id": "folder-1", "name": "Folder 1", "isFolder": True}],
    )

    response = await connector_check_duplicates(
        connector_type="onedrive",
        body=body,
        request=MagicMock(),
        connector_service=connector_service,
        session_manager=session_manager,
        user=user,
    )

    assert isinstance(response, JSONResponse)
    data = json.loads(response.body.decode())
    assert "existing.pdf" in data["duplicate_names"]
    assert "new_file.docx" not in data["duplicate_names"]
    assert data["total_files"] == 2
