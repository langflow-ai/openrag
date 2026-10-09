import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _permissive_rbac():
    """RBAC stub that grants everything.

    Unit tests pin OPENRAG_RBAC_ENFORCE=true (tests/unit/conftest.py), and every
    sync now resolves knowledge:delete:anonymous up front to decide whether
    orphan cleanup may touch ownerless chunks (see delete_orphan_documents).
    """
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)
    return rbac


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
    expanded_response = {
        "files": [
            {"id": "file-1", "name": "document.pdf"},
            {"id": "file-2", "name": "program.exe"},
        ]
    }
    connector.list_files = AsyncMock(return_value=expanded_response)
    connector.list_selected_files = AsyncMock(return_value=expanded_response)
    connector.cfg = MagicMock()

    service.get_connector = AsyncMock(return_value=connector)

    # When creating a custom task, we'll return a dummy task ID
    service.task_service.create_custom_task = AsyncMock(return_value="dummy-task-id")

    # Verify that calling sync_specific_files succeeds (no ValueError raised!)
    task_id = await service.sync_specific_files(
        connection_id="conn-id",
        user_id="user-id",
        file_ids=["folder-id"],
        jwt_token="jwt",
        allow_anonymous_delete=True,
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
        allow_anonymous_delete=True,
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
    expanded_files = {
        "files": [
            {"id": "file-1", "name": "existing.pdf", "mimeType": "application/pdf"},
            {
                "id": "file-2",
                "name": "new_file.docx",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        ]
    }
    connector.list_files = AsyncMock(return_value=expanded_files)
    connector.list_selected_files = AsyncMock(return_value=expanded_files)
    connector.cfg = MagicMock()
    connector_service.get_connector = AsyncMock(return_value=connector)

    # Mock session_manager and OpenSearch client
    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    # Mock search return value: existing.pdf exists, new_file.docx does not
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {"filenames": {"buckets": [{"key": "existing.pdf", "doc_count": 1}]}}
        }
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
    assert data["duplicate_count"] == 1
    assert data["duplicate_files"] == [
        {
            "id": "file-1",
            "name": "existing.pdf",
            "mimeType": "application/pdf",
            "isFolder": False,
        }
    ]
    assert data["non_duplicate_files"] == [
        {
            "id": "file-2",
            "name": "new_file.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "isFolder": False,
        }
    ]


@pytest.mark.asyncio
async def test_connector_check_duplicates_bucket_filter_is_existence_based():
    """Bucket-kind connectors (Azure Blob/S3/COS) select whole buckets, not
    individual files, so check-duplicates must accept bucket_filter and list
    files from those buckets. Classification must be existence-based — any
    blob already ingested under this connector_type is a duplicate — the same
    semantics the filename-based OAuth check uses, NOT the modified-time
    "changed" gate the real bucket_filter sync uses to silently skip unchanged
    blobs. Otherwise re-selecting an up-to-date bucket reports zero duplicates
    and the overwrite dialog never appears."""
    import json

    from fastapi.responses import JSONResponse

    from api.connectors import ConnectorCheckDuplicatesBody, connector_check_duplicates

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
    connector.bucket_names = None
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                # Already ingested (remote timestamp is irrelevant) -> duplicate.
                {
                    "id": "bucket::already-ingested.pdf",
                    "name": "already-ingested.pdf",
                    "mimeType": "application/pdf",
                    "modified_time": "2026-01-01T00:00:00Z",
                },
                # Not ingested yet -> new.
                {
                    "id": "bucket::new.pdf",
                    "name": "new.pdf",
                    "mimeType": "application/pdf",
                    "modified_time": "2026-07-13T00:00:00Z",
                },
            ]
        }
    )
    connector_service.get_connector = AsyncMock(return_value=connector)

    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "unique_connector_file_ids": {
                    "buckets": [{"key": "bucket::already-ingested.pdf"}],
                },
                "unique_document_ids": {"buckets": []},
                "unique_filenames": {"buckets": []},
            }
        }
    )
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    user = MagicMock()
    user.user_id = "user-id"
    user.jwt_token = "jwt-token"

    body = ConnectorCheckDuplicatesBody(
        connection_id="conn-id",
        bucket_filter=["bucket"],
    )

    response = await connector_check_duplicates(
        connector_type="azure_blob",
        body=body,
        request=MagicMock(),
        connector_service=connector_service,
        session_manager=session_manager,
        user=user,
    )

    assert isinstance(response, JSONResponse)
    data = json.loads(response.body.decode())
    assert data["duplicate_names"] == ["already-ingested.pdf"]
    assert data["duplicate_count"] == 1
    assert data["total_files"] == 2
    assert [f["id"] for f in data["non_duplicate_files"]] == ["bucket::new.pdf"]


@pytest.mark.asyncio
async def test_connector_sync_skip_duplicates_returns_no_files_when_all_selected_are_duplicates(
    monkeypatch,
):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr(connectors_api, "_ensure_index_exists", AsyncMock(), raising=False)
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))

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
    connector.cfg = MagicMock()
    expanded_files = {
        "files": [
            {"id": "file-1", "name": "existing.pdf", "mimeType": "application/pdf"},
            {
                "id": "file-2",
                "name": "existing.docx",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        ]
    }
    connector.list_files = AsyncMock(return_value=expanded_files)
    connector.list_selected_files = AsyncMock(return_value=expanded_files)
    connector_service.get_connector = AsyncMock(return_value=connector)
    connector_service.sync_specific_files = AsyncMock(return_value="task-id")

    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {
                "filenames": {
                    "buckets": [
                        {"key": "existing.pdf", "doc_count": 1},
                        {"key": "existing.docx", "doc_count": 1},
                    ]
                }
            }
        }
    )

    response = await connectors_api.connector_sync(
        connector_type="google_drive",
        body=connectors_api.ConnectorSyncBody(
            selected_files=[{"id": "folder-id", "name": "Folder", "isFolder": True}],
            replace_duplicates=False,
        ),
        request=MagicMock(),
        connector_service=connector_service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="user-id", jwt_token="jwt-token", db_user_id="user-id"),
        rbac=_permissive_rbac(),
    )

    assert response.status_code == 200
    data = json.loads(response.body.decode())
    assert data["status"] == "no_files"
    assert data["duplicate_count"] == 2
    assert "already exist" in data["message"]
    connector_service.sync_specific_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_connector_sync_skip_duplicates_submits_only_expanded_non_duplicates(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))

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
    connector.cfg = MagicMock()
    expanded_files = {
        "files": [
            {"id": "file-1", "name": "existing.pdf", "mimeType": "application/pdf"},
            {
                "id": "file-2",
                "name": "new_file.docx",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        ]
    }
    connector.list_files = AsyncMock(return_value=expanded_files)
    connector.list_selected_files = AsyncMock(return_value=expanded_files)
    connector_service.get_connector = AsyncMock(return_value=connector)
    connector_service.sync_specific_files = AsyncMock(return_value="task-id")

    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    opensearch_client.search = AsyncMock(
        return_value={
            "aggregations": {"filenames": {"buckets": [{"key": "existing.pdf", "doc_count": 1}]}}
        }
    )

    response = await connectors_api.connector_sync(
        connector_type="sharepoint",
        body=connectors_api.ConnectorSyncBody(
            selected_files=[{"id": "folder-id", "name": "Folder", "isFolder": True}],
            replace_duplicates=False,
        ),
        request=MagicMock(),
        connector_service=connector_service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="user-id", jwt_token="jwt-token", db_user_id="user-id"),
        rbac=_permissive_rbac(),
    )

    assert response.status_code == 201
    connector_service.sync_specific_files.assert_awaited_once()
    args = connector_service.sync_specific_files.await_args.args
    kwargs = connector_service.sync_specific_files.await_args.kwargs
    assert args[2] == ["file-2"]
    assert kwargs["file_infos"] == [
        {
            "id": "file-2",
            "name": "new_file.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "isFolder": False,
        }
    ]


@pytest.mark.asyncio
async def test_connector_sync_does_not_report_all_duplicates_when_expansion_is_empty(monkeypatch):
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api.TelemetryClient, "send_event", AsyncMock())
    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))

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
    connector.cfg = MagicMock()
    connector.list_files = AsyncMock(return_value={"files": []})
    connector_service.get_connector = AsyncMock(return_value=connector)
    connector_service.sync_specific_files = AsyncMock(return_value="task-id")

    session_manager = MagicMock()
    opensearch_client = AsyncMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    response = await connectors_api.connector_sync(
        connector_type="google_drive",
        body=connectors_api.ConnectorSyncBody(
            selected_files=[{"id": "folder-id", "name": "Folder", "isFolder": True}],
            replace_duplicates=False,
        ),
        request=MagicMock(),
        connector_service=connector_service,
        session_manager=session_manager,
        user=SimpleNamespace(user_id="user-id", jwt_token="jwt-token", db_user_id="user-id"),
        rbac=_permissive_rbac(),
    )

    assert response.status_code == 201
    connector_service.sync_specific_files.assert_awaited_once()
    args = connector_service.sync_specific_files.await_args.args
    kwargs = connector_service.sync_specific_files.await_args.kwargs
    assert args[2] == ["folder-id"]
    assert kwargs["file_infos"] == [{"id": "folder-id", "name": "Folder", "isFolder": True}]


@pytest.mark.asyncio
async def test_check_duplicates_rejects_a_request_that_names_nothing():
    """A check with neither selected_files nor bucket_filter used to answer with
    an empty duplicate list, which reads to the caller as "checked, found
    nothing" — the UI then ingests without ever offering the overwrite choice,
    indistinguishable from a check that genuinely found none. Say the request
    asked about nothing instead.
    """
    import json

    from fastapi.responses import JSONResponse

    from api.connectors import ConnectorCheckDuplicatesBody, connector_check_duplicates

    response = await connector_check_duplicates(
        connector_type="ibm_cos",
        body=ConnectorCheckDuplicatesBody(connection_id="conn-id"),
        request=MagicMock(),
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        user=MagicMock(user_id="u1", jwt_token="t"),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    data = json.loads(response.body.decode())
    assert "duplicate_names" not in data
    assert "bucket_filter" in data["error"]


@pytest.mark.asyncio
async def test_bucket_duplicate_check_logs_its_outcome(monkeypatch):
    """The counts behind the answer are logged, so "the dialog never appeared"
    can be settled from the server rather than from a browser network tab."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")
    monkeypatch.setattr(
        connectors_api,
        "get_synced_file_ids_for_connector",
        AsyncMock(return_value=(["b::synced.pdf"], [], "connector_file_id")),
    )

    indexed = {"taken.pdf"}

    async def search(*, index, body):
        terms = body["query"].get("terms")
        if terms is not None:
            asked = terms["filename"]
            return {
                "aggregations": {
                    "filenames": {"buckets": [{"key": n} for n in asked if n in indexed]}
                }
            }
        return {
            "aggregations": {
                "connector_file_ids": {"buckets": []},
                "document_ids": {"buckets": []},
            }
        }

    client = AsyncMock()
    client.search = AsyncMock(side_effect=search)
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=client)

    connector = MagicMock()
    connector.bucket_names = None
    connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "b::synced.pdf", "name": "synced.pdf"},
                {"id": "b::taken.pdf", "name": "taken.pdf"},
                {"id": "b::fresh.pdf", "name": "fresh.pdf"},
            ],
            "next_page_token": None,
        }
    )

    # The project logger writes straight to stderr rather than propagating to the
    # stdlib root logger, so assert on the call instead of on caplog.
    logged = []
    monkeypatch.setattr(connectors_api.logger, "info", lambda msg, **kw: logged.append((msg, kw)))

    await connectors_api._classify_bucket_connector_duplicates(
        connector=connector,
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=session_manager,
        user_id="u1",
        jwt_token="t",
    )

    summary = next(kw for msg, kw in logged if msg == "Duplicate check complete")
    assert summary["listed"] == 3
    assert summary["already_synced_here"] == 1
    assert summary["name_taken_elsewhere"] == 1
    assert summary["duplicates"] == 2
    assert summary["new_files"] == 1


@pytest.mark.asyncio
async def test_bucket_duplicate_check_logs_an_empty_listing(monkeypatch):
    """Zero duplicates because the bucket listing came back empty is a different
    fact from zero duplicates among files that were listed."""
    from api import connectors as connectors_api

    connector = MagicMock()
    connector.bucket_names = None
    connector.list_files = AsyncMock(return_value={"files": [], "next_page_token": None})

    logged = []
    monkeypatch.setattr(connectors_api.logger, "info", lambda msg, **kw: logged.append((msg, kw)))

    result = await connectors_api._classify_bucket_connector_duplicates(
        connector=connector,
        connector_type="ibm_cos",
        bucket_filter=["b"],
        session_manager=MagicMock(),
        user_id="u1",
        jwt_token="t",
    )

    assert result["duplicate_count"] == 0
    assert any(msg == "Duplicate check found nothing to check" for msg, _ in logged)


@pytest.mark.asyncio
async def test_selected_files_check_logs_an_empty_expansion(monkeypatch):
    """Folders that expand to nothing answer "no duplicates" without ever
    comparing anything. Logged against what the caller selected, so the OAuth
    connectors are as diagnosable as the bucket ones."""
    from api import connectors as connectors_api

    connector = MagicMock()
    connector.cfg = MagicMock()
    connector.list_selected_files = AsyncMock(return_value={"files": []})

    logged = []
    monkeypatch.setattr(connectors_api.logger, "info", lambda msg, **kw: logged.append((msg, kw)))

    result = await connectors_api._classify_connector_duplicates(
        connector=connector,
        connector_type="onedrive",
        selected_files_raw=[
            {"id": "folder-1", "name": "Empty 1", "isFolder": True},
            {"id": "folder-2", "name": "Empty 2", "isFolder": True},
        ],
        session_manager=MagicMock(),
        user_id="u1",
        jwt_token="t",
    )

    assert result["duplicate_count"] == 0
    summary = next(kw for msg, kw in logged if msg == "Duplicate check found nothing to check")
    assert summary["connector_type"] == "onedrive"
    assert summary["selected"] == 2


@pytest.mark.asyncio
async def test_selected_files_check_logs_when_no_name_is_comparable(monkeypatch):
    """Files expanded but none produced a name to compare, so the index was
    never queried — every file is reported new without having been checked."""
    from api import connectors as connectors_api

    connector = MagicMock()
    connector.cfg = None  # not a cfg-backed connector: use the raw selection

    logged = []
    monkeypatch.setattr(connectors_api.logger, "info", lambda msg, **kw: logged.append((msg, kw)))

    result = await connectors_api._classify_connector_duplicates(
        connector=connector,
        connector_type="google_drive",
        selected_files_raw=[{"id": "f1", "name": "", "mimeType": ""}],
        session_manager=MagicMock(),
        user_id="u1",
        jwt_token="t",
    )

    assert result["duplicate_count"] == 0
    summary = next(
        kw for msg, kw in logged if msg == "Duplicate check skipped: no comparable filenames"
    )
    assert summary["connector_type"] == "google_drive"
    assert summary["listed"] == 1


@pytest.mark.asyncio
async def test_selected_files_check_names_its_connector_in_the_summary(monkeypatch):
    """One grep covers both connector families; connector_type says which path
    the line came from."""
    from api import connectors as connectors_api

    monkeypatch.setattr(connectors_api, "get_index_name", lambda: "idx")

    client = AsyncMock()
    client.search = AsyncMock(
        return_value={"aggregations": {"filenames": {"buckets": [{"key": "taken.pdf"}]}}}
    )
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=client)

    connector = MagicMock()
    connector.cfg = None

    logged = []
    monkeypatch.setattr(connectors_api.logger, "info", lambda msg, **kw: logged.append((msg, kw)))

    await connectors_api._classify_connector_duplicates(
        connector=connector,
        connector_type="sharepoint",
        selected_files_raw=[
            {"id": "f1", "name": "taken.pdf", "mimeType": "application/pdf"},
            {"id": "f2", "name": "fresh.pdf", "mimeType": "application/pdf"},
        ],
        session_manager=session_manager,
        user_id="u1",
        jwt_token="t",
    )

    summary = next(kw for msg, kw in logged if msg == "Duplicate check complete")
    assert summary["connector_type"] == "sharepoint"
    assert summary["selected"] == 2
    assert summary["duplicates"] == 1
    assert summary["new_files"] == 1
