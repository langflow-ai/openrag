"""Replacing a shared document takes knowledge:delete:anonymous on every ingest path.

Ownerless ("share-all") chunks are visible to the whole instance, so an
overwrite whose filename belongs to one deletes it for everybody. The delete
that decides this — ``TaskProcessor.delete_document_by_filename`` — took the
caller's permission as a parameter that defaulted to True, and only connector
sync resolved it. Local upload, the Langflow pipeline and S3 never did, so
through them any user could replace a shared document: it vanished for everyone
else and came back owned by the uploader.

Three things are pinned here. Each of those processors hands its caller's
permission to the delete. Each entry point resolves that permission, or says
outright why it does not need to. And nothing on the way down has a default to
fall back on again.
"""

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from connectors.service import ConnectorService
from models.processors import (
    ConnectorFileProcessor,
    DocumentFileProcessor,
    LangflowFileProcessor,
    S3FileProcessor,
    TaskProcessor,
)
from models.tasks import FileTask, TaskStatus, UploadTask
from services.task_service import TaskService
from session_manager import User
from utils.opensearch_queries import build_owner_or_shared_filter

SHARED_DOC = "Leave.Policy.pdf"
UPLOADER = "user-b"
PERMISSION = "knowledge:delete:anonymous"


# ---------------------------------------------------------------------------
# The processors: the permission reaches the delete
# ---------------------------------------------------------------------------


def _index_holding_one_shared_document(monkeypatch):
    """One ownerless document under SHARED_DOC, and nothing UPLOADER owns.

    The user client answers a delete scope with the shared chunk only when that
    scope can match an ownerless one, which is the whole question. Deletes and
    the refresh that follows go through the admin client.
    """
    admin_client = AsyncMock()
    admin_client.indices = AsyncMock()
    admin_client.delete = AsyncMock(return_value={"result": "deleted"})
    # delete_document_by_filename imports these at call time; the refresh after
    # a delete reads the module-level one.
    monkeypatch.setattr("config.settings.clients", SimpleNamespace(opensearch=admin_client))
    monkeypatch.setattr("config.settings.get_index_name", lambda: "test-index")
    monkeypatch.setattr("models.processors.clients", SimpleNamespace(opensearch=admin_client))

    async def search(*, index, body, **kwargs):
        reaches_shared = build_owner_or_shared_filter(UPLOADER) in body["query"]["bool"]["filter"]
        hits = [{"_id": "shared-chunk-1"}] if reaches_shared else []
        return {"_scroll_id": None, "hits": {"hits": hits}}

    user_client = AsyncMock()
    user_client.search = AsyncMock(side_effect=search)
    return user_client, admin_client


def _local_upload(user_client, tmp_path, allow_anonymous_delete):
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)
    processor = DocumentFileProcessor(
        document_service=MagicMock(),
        models_service=MagicMock(),
        owner_user_id=UPLOADER,
        jwt_token="token",
        replace_duplicates=True,
        session_manager=session_manager,
        allow_anonymous_delete=allow_anonymous_delete,
    )
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed", "id": "h"})
    item = tmp_path / "upload.pdf"
    item.write_bytes(b"new content")
    return processor, str(item), processor.process_document_standard


def _langflow_upload(user_client, tmp_path, allow_anonymous_delete):
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)
    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "h"}
    )
    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id=UPLOADER,
        jwt_token="token",
        replace_duplicates=True,
        allow_anonymous_delete=allow_anonymous_delete,
    )
    item = tmp_path / "upload.pdf"
    item.write_bytes(b"new content")
    return processor, str(item), langflow_file_service.upload_and_ingest_file


def _s3_upload(user_client, tmp_path, allow_anonymous_delete):
    document_service = MagicMock()
    document_service.session_manager.get_user_opensearch_client = MagicMock(
        return_value=user_client
    )
    processor = S3FileProcessor(
        document_service,
        bucket="bucket",
        s3_client=MagicMock(),
        owner_user_id=UPLOADER,
        jwt_token="token",
        models_service=MagicMock(),
        docling_service=MagicMock(),
        replace_duplicates=True,
        allow_anonymous_delete=allow_anonymous_delete,
    )
    processor.s3_client.head_object = MagicMock(return_value={"ContentLength": 10})
    processor.process_document_standard = AsyncMock(return_value={"status": "indexed", "id": "h"})
    # The S3 key is the indexed filename.
    return processor, SHARED_DOC, processor.process_document_standard


# ConnectorFileProcessor already carried the permission; its own tests cover it.
PREVIOUSLY_UNGATED = [
    pytest.param(_local_upload, id="local-upload"),
    pytest.param(_langflow_upload, id="langflow"),
    pytest.param(_s3_upload, id="s3"),
]


async def _overwrite(processor, item):
    # The duplicate check is owner-agnostic: a shared document is visible to
    # everyone, so every uploader is told the name is taken.
    processor.check_filename_exists = AsyncMock(return_value=True)
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path=item, filename=SHARED_DOC)
    with patch("models.processors.hash_id", return_value="hash-1"):
        await processor.process_item(upload_task, item, file_task)
    return file_task


@pytest.mark.asyncio
@pytest.mark.parametrize("build", PREVIOUSLY_UNGATED)
async def test_overwrite_without_the_permission_leaves_the_shared_document_alone(
    build, monkeypatch, tmp_path
):
    user_client, admin_client = _index_holding_one_shared_document(monkeypatch)
    processor, item, ingest = build(user_client, tmp_path, allow_anonymous_delete=False)

    file_task = await _overwrite(processor, item)

    admin_client.delete.assert_not_awaited()
    ingest.assert_not_awaited()
    # Nothing was deleted, so there is nothing to replace: the file resolves as
    # a duplicate the uploader may not overwrite.
    assert file_task.status == TaskStatus.SKIPPED
    assert file_task.result["reason"] == "duplicate_filename"


@pytest.mark.asyncio
@pytest.mark.parametrize("build", PREVIOUSLY_UNGATED)
async def test_overwrite_with_the_permission_still_replaces_it(build, monkeypatch, tmp_path):
    """Otherwise the gate would simply be breaking overwrite for everyone."""
    user_client, admin_client = _index_holding_one_shared_document(monkeypatch)
    processor, item, ingest = build(user_client, tmp_path, allow_anonymous_delete=True)

    file_task = await _overwrite(processor, item)

    admin_client.delete.assert_awaited_once()
    assert admin_client.delete.await_args.kwargs["id"] == "shared-chunk-1"
    ingest.assert_awaited_once()
    assert file_task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# The entry points: the permission is resolved, or explicitly not needed
# ---------------------------------------------------------------------------


def _rbac(granted: bool):
    # Unit tests run with RBAC enforced (tests/unit/conftest.py), so the lookup
    # really goes to the RBAC service.
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=granted)
    return rbac


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _user():
    return User(user_id=UPLOADER, email="b@example.com", name="User B", jwt_token="Bearer tok")


def _upload_file():
    upload = MagicMock(spec=UploadFile)
    upload.filename = SHARED_DOC
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"%PDF-new")
    return upload


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", [True, False])
@pytest.mark.parametrize(
    "langflow_disabled, creates_task_with",
    [
        pytest.param(True, "create_upload_task", id="traditional"),
        pytest.param(False, "create_langflow_upload_task", id="langflow"),
    ],
)
async def test_upload_router_resolves_the_permission_for_both_pipelines(
    granted, langflow_disabled, creates_task_with, monkeypatch
):
    from api.router import upload_ingest_router

    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    task_service = MagicMock()
    create_task = AsyncMock(return_value="task-1")
    setattr(task_service, creates_task_with, create_task)
    rbac = _rbac(granted)
    temp_file = MagicMock()
    temp_file.name = "/tmp/upload.pdf"

    with (
        patch("api.router.get_openrag_config") as config,
        patch("api.router.tempfile.NamedTemporaryFile", return_value=temp_file),
        patch("api.router.open", create=True),
        patch("utils.file_utils.safe_unlink"),
    ):
        config.return_value.knowledge.disable_ingest_with_langflow = langflow_disabled
        response = await upload_ingest_router(
            request=_request(),
            file=[_upload_file()],
            session_id=None,
            settings_json=None,
            tweaks_json=None,
            replace_duplicates="true",
            create_filter="false",
            preview="false",
            document_service=MagicMock(),
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=task_service,
            user=_user(),
            rbac=rbac,
        )

    assert response.status_code == 202
    assert rbac.has_permission.await_args.args[1] == PERMISSION
    assert create_task.await_args.kwargs["allow_anonymous_delete"] is granted


def test_over_http_the_permission_comes_from_rbac_and_never_from_the_caller(monkeypatch, tmp_path):
    """Through FastAPI rather than as a function call, because this is the
    binding a direct call cannot show: a parameter FastAPI does not recognise
    as a dependency is read from the query string, where the caller could
    simply grant it to themselves."""
    from api import router as router_api

    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")
    rbac = _rbac(False)

    app = FastAPI()
    app.add_api_route("/router/upload_ingest", router_api.upload_ingest_router, methods=["POST"])
    app.dependency_overrides[router_api.get_document_service] = lambda: MagicMock()
    app.dependency_overrides[router_api.get_langflow_file_service] = lambda: MagicMock()
    app.dependency_overrides[router_api.get_session_manager] = lambda: MagicMock()
    app.dependency_overrides[router_api.get_task_service] = lambda: task_service
    app.dependency_overrides[router_api.get_current_user] = _user
    app.dependency_overrides[router_api.get_rbac_service] = lambda: rbac

    with patch("api.router.get_openrag_config") as config, TestClient(app) as client:
        config.return_value.knowledge.disable_ingest_with_langflow = False
        response = client.post(
            "/router/upload_ingest?allow_anonymous_delete=true",
            files={"file": (SHARED_DOC, b"%PDF-new", "application/pdf")},
            data={"replace_duplicates": "true", "allow_anonymous_delete": "true"},
        )

    assert response.status_code == 202, response.text
    kwargs = task_service.create_langflow_upload_task.await_args.kwargs
    assert kwargs["replace_duplicates"] is True
    assert kwargs["allow_anonymous_delete"] is False


@pytest.mark.asyncio
async def test_v1_ingest_hands_the_router_what_it_needs_to_resolve_the_permission():
    """The v1 endpoint calls the router as a plain function, where a Depends()
    default is never resolved: left out, ``rbac`` would arrive as the Depends
    marker itself."""
    from api.v1.documents import ingest_endpoint

    request, rbac = _request(), _rbac(True)

    with patch("api.v1.documents.upload_ingest_router", new=AsyncMock()) as router:
        await ingest_endpoint(
            request=request,
            file=[MagicMock()],
            session_id=None,
            settings=None,
            tweaks=None,
            replace_duplicates="true",
            create_filter="false",
            document_service=MagicMock(),
            langflow_file_service=MagicMock(),
            session_manager=MagicMock(),
            task_service=MagicMock(),
            user=_user(),
            rbac=rbac,
        )

    assert router.await_args.kwargs["request"] is request
    assert router.await_args.kwargs["rbac"] is rbac


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", [True, False])
async def test_s3_bucket_upload_resolves_the_permission(granted, monkeypatch):
    from api import upload as upload_api

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": SHARED_DOC}]}]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = paginator
    monkeypatch.setattr(upload_api.boto3, "client", MagicMock(return_value=s3_client))

    built: dict = {}

    class FakeProcessor:
        def __init__(self, *args, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr("models.processors.S3FileProcessor", FakeProcessor)
    task_service = MagicMock()
    task_service.create_custom_task = AsyncMock(return_value="task-1")
    rbac = _rbac(granted)

    response = await upload_api.upload_bucket(
        upload_api.UploadBucketBody(s3_url="s3://bucket/prefix", replace_duplicates=True),
        request=_request(),
        task_service=task_service,
        models_service=MagicMock(),
        docling_service=MagicMock(),
        session_manager=MagicMock(),
        user=_user(),
        rbac=rbac,
    )

    assert response.status_code == 201
    assert rbac.has_permission.await_args.args[1] == PERMISSION
    assert built["allow_anonymous_delete"] is granted


@pytest.mark.asyncio
async def test_directory_upload_cannot_replace_so_it_asks_for_nothing(monkeypatch, tmp_path):
    from api import upload as upload_api

    (tmp_path / "doc.txt").write_text("hello")
    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task-1")

    await upload_api.upload_path(
        upload_api.UploadPathBody(path=str(tmp_path)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=_user(),
    )

    kwargs = task_service.create_upload_task.await_args.kwargs
    # The two go together: with no way to ask for a replacement, no delete is
    # ever attempted, and the flag stays off in case that changes.
    assert "replace_duplicates" not in kwargs
    assert kwargs["allow_anonymous_delete"] is False


@pytest.mark.asyncio
async def test_langflow_single_file_upload_cannot_replace_so_it_asks_for_nothing(
    monkeypatch, tmp_path
):
    from api import langflow_files

    monkeypatch.setattr(langflow_files.tempfile, "gettempdir", lambda: str(tmp_path))
    task_service = MagicMock()
    task_service.create_langflow_upload_task = AsyncMock(return_value="task-1")

    response = await langflow_files.upload_and_ingest_user_file(
        file=_upload_file(),
        session_id=None,
        settings_json=None,
        tweaks_json=None,
        langflow_file_service=MagicMock(),
        session_manager=MagicMock(),
        task_service=task_service,
        user=_user(),
    )

    assert response.status_code == 202, json.loads(response.body)
    kwargs = task_service.create_langflow_upload_task.await_args.kwargs
    assert "replace_duplicates" not in kwargs
    assert kwargs["allow_anonymous_delete"] is False


# ---------------------------------------------------------------------------
# The way down: the task service hands it on, and nothing defaults it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize(
    "create_task, processor_class, extra",
    [
        pytest.param("create_upload_task", "DocumentFileProcessor", {}, id="traditional"),
        pytest.param(
            "create_langflow_upload_task",
            "LangflowFileProcessor",
            {"langflow_file_service": AsyncMock(), "session_manager": AsyncMock()},
            id="langflow",
        ),
    ],
)
async def test_task_service_hands_the_permission_to_the_processor(
    allowed, create_task, processor_class, extra, monkeypatch
):
    built: dict = {}

    class FakeProcessor:
        def __init__(self, *args, **kwargs):
            built.update(kwargs)

    monkeypatch.setattr(f"models.processors.{processor_class}", FakeProcessor)
    service = TaskService()
    monkeypatch.setattr(service, "create_custom_task", AsyncMock(return_value="task-1"))

    await getattr(service, create_task)(
        user_id=UPLOADER,
        file_paths=["/tmp/x.pdf"],
        allow_anonymous_delete=allowed,
        **extra,
    )

    assert built["allow_anonymous_delete"] is allowed


@pytest.mark.parametrize(
    "takes_the_permission",
    [
        TaskProcessor.resolve_duplicate_filename,
        TaskProcessor.delete_document_by_filename,
        DocumentFileProcessor.__init__,
        ConnectorFileProcessor.__init__,
        S3FileProcessor.__init__,
        LangflowFileProcessor.__init__,
        TaskService.create_upload_task,
        TaskService.create_langflow_upload_task,
        ConnectorService.sync_connector_files,
        ConnectorService.sync_specific_files,
    ],
    ids=lambda function: function.__qualname__,
)
def test_the_permission_has_no_default_anywhere_on_the_way_down(takes_the_permission):
    """A default is how this was lost: it was True, and every caller that never
    resolved the permission inherited it without a line of code saying so. With
    none, a caller that leaves it out fails where it is written."""
    parameter = inspect.signature(takes_the_permission).parameters["allow_anonymous_delete"]

    assert parameter.default is inspect.Parameter.empty
