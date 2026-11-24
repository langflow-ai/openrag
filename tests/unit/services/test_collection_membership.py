"""Filter membership on ingest: the access check, the stamp, and scoped search."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from api.knowledge_filter import normalize_query_data
from api.v1._filter_resolution import _strip_wildcards
from models.tasks import FileTask, TaskStatus, UploadTask
from services import collection_membership
from services.collection_membership import (
    apply_collection_labels,
    build_own_document_chunks_query,
    collection_label,
    normalize_filter_ids,
    validate_ingest_filter_ids,
)
from services.search_service import _build_search_filter_clauses
from session_manager import User
from utils.opensearch_queries import build_filter_clauses

USER = User(user_id="user-1", email="u@example.com", name="User", jwt_token="Bearer tok")


# --- access check -----------------------------------------------------------


class _FilterService:
    def __init__(self, visible: set[str]):
        self.visible = visible
        self.calls: list[str] = []

    async def get_knowledge_filter(self, filter_id, user_id=None, jwt_token=None):
        self.calls.append(filter_id)
        if filter_id in self.visible:
            return {"success": True, "filter": {"id": filter_id}}
        return {"success": False, "error": "Knowledge filter not found"}


def _allow(monkeypatch, allowed: bool):
    monkeypatch.setattr(
        "auth.permission_dependencies.has_effective_permission",
        AsyncMock(return_value=allowed),
    )


@pytest.mark.asyncio
async def test_validate_accepts_visible_filters_with_edit_permission(monkeypatch):
    _allow(monkeypatch, True)
    service = _FilterService({"f1", "f2"})

    result = await validate_ingest_filter_ids(
        ["f1", "f2"], request=Mock(), user=USER, rbac=Mock(), knowledge_filter_service=service
    )

    assert result is None
    assert service.calls == ["f1", "f2"]


@pytest.mark.asyncio
async def test_validate_rejects_unknown_filter_with_404(monkeypatch):
    _allow(monkeypatch, True)

    result = await validate_ingest_filter_ids(
        ["f1", "missing"],
        request=Mock(),
        user=USER,
        rbac=Mock(),
        knowledge_filter_service=_FilterService({"f1"}),
    )

    assert result.status_code == 404
    assert json.loads(result.body)["filter_id"] == "missing"


@pytest.mark.asyncio
async def test_validate_rejects_caller_without_edit_permission_with_403(monkeypatch):
    _allow(monkeypatch, False)
    service = _FilterService({"f1"})

    result = await validate_ingest_filter_ids(
        ["f1"], request=Mock(), user=USER, rbac=Mock(), knowledge_filter_service=service
    )

    assert result.status_code == 403
    assert service.calls == []


def test_normalize_filter_ids_drops_blanks_and_duplicates():
    assert normalize_filter_ids(["a", " ", "b", "a", "", None]) == ["a", "b"]
    assert normalize_filter_ids("a") == ["a"]
    assert normalize_filter_ids(None) == []


# --- router: rejected before a task is created --------------------------------

_RBAC = SimpleNamespace(has_permission=AsyncMock(return_value=True))


@pytest.mark.asyncio
async def test_router_rejects_unknown_filter_before_creating_a_task(monkeypatch):
    from api import router

    _allow(monkeypatch, True)
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock()
    task_service.create_langflow_upload_task = AsyncMock()

    response = await router.upload_ingest_router(
        request=Mock(),
        file=[MagicMock()],
        session_id=None,
        existing_task_id=None,
        rejected_files=None,
        settings_json=None,
        tweaks_json=None,
        replace_duplicates="true",
        create_filter="false",
        preview="false",
        filter_ids=["missing"],
        document_service=Mock(),
        langflow_file_service=Mock(),
        session_manager=Mock(),
        task_service=task_service,
        user=USER,
        rbac=_RBAC,
        knowledge_filter_service=_FilterService(set()),
    )

    assert response.status_code == 404
    task_service.create_upload_task.assert_not_awaited()
    task_service.create_langflow_upload_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("disable_langflow", [True, False])
async def test_router_forwards_filter_ids_on_both_ingest_paths(monkeypatch, disable_langflow):
    from api import router

    _allow(monkeypatch, True)
    monkeypatch.setattr(
        router,
        "get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(disable_ingest_with_langflow=disable_langflow)
        ),
    )
    monkeypatch.setattr("api.documents._ensure_index_exists", AsyncMock())
    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="t1")
    task_service.create_langflow_upload_task = AsyncMock(return_value="t1")
    upload = MagicMock(filename="a.txt", content_type="text/plain")
    monkeypatch.setattr(router, "read_upload_within_limit", AsyncMock(return_value=b"hi"))

    response = await router.upload_ingest_router(
        request=Mock(),
        file=[upload],
        session_id=None,
        existing_task_id=None,
        rejected_files=None,
        settings_json=None,
        tweaks_json=None,
        replace_duplicates="true",
        create_filter="false",
        preview="false",
        filter_ids=["f1", "f1", "f2"],
        document_service=Mock(),
        langflow_file_service=Mock(),
        session_manager=Mock(),
        task_service=task_service,
        user=USER,
        rbac=_RBAC,
        knowledge_filter_service=_FilterService({"f1", "f2"}),
    )

    assert response.status_code == 202
    create = (
        task_service.create_upload_task
        if disable_langflow
        else task_service.create_langflow_upload_task
    )
    assert create.await_args.kwargs["filter_ids"] == ["f1", "f2"]
    assert json.loads(response.body)["filter_ids"] == ["f1", "f2"]


# --- the stamp ---------------------------------------------------------------


class _VersionConflict(Exception):
    status_code = 409


class _FakeOpenSearch:
    """Filters with sequence numbers, so conditional writes behave like OpenSearch."""

    def __init__(self, filters: dict[str, dict], ubq_responses: list[dict] | None = None):
        self.filters = filters
        self.seq_no = dict.fromkeys(filters, 0)
        self.update_by_query_calls: list[dict] = []
        self.filter_updates: list[tuple[str, dict]] = []
        self.ubq_responses = list(ubq_responses or [])
        # Runs once, between the read and the conditional write of a filter.
        self.before_write = None

    async def get(self, index, id):
        assert index == "knowledge_filters"
        if id in self.filters:
            return {
                "found": True,
                "_source": dict(self.filters[id]),
                "_seq_no": self.seq_no[id],
                "_primary_term": 1,
            }
        return {"found": False}

    async def update_by_query(self, index, body, **kwargs):
        self.update_by_query_calls.append({"index": index, "body": body, **kwargs})
        if self.ubq_responses:
            return self.ubq_responses.pop(0)
        return {"updated": 1, "version_conflicts": 0, "failures": []}

    def edit(self, id, **fields):
        """A concurrent writer, e.g. someone saving the filter."""
        self.filters[id] = {**self.filters[id], **fields}
        self.seq_no[id] += 1

    async def update(self, index, id, body, if_seq_no=None, if_primary_term=None, **kwargs):
        if self.before_write is not None:
            hook, self.before_write = self.before_write, None
            hook()
        if if_seq_no is not None and if_seq_no != self.seq_no[id]:
            raise _VersionConflict("version conflict")
        self.filter_updates.append((id, body["doc"]))
        self.edit(id, **body["doc"])
        return {"result": "updated"}


def _install(monkeypatch, fake):
    monkeypatch.setattr("config.settings.clients", SimpleNamespace(opensearch=fake))
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")


def _task(*file_tasks: FileTask) -> UploadTask:
    return UploadTask(
        task_id="t1",
        total_files=len(file_tasks),
        file_tasks={ft.file_path: ft for ft in file_tasks},
    )


def _file(path, status, document_id="doc-" + "x", filter_ids=("f1",)):
    return FileTask(
        file_path=path, status=status, document_id=document_id, filter_ids=tuple(filter_ids)
    )


def _query_data(filters=None):
    return json.dumps({"filters": filters or {"data_sources": ["*"]}, "limit": 10})


@pytest.mark.asyncio
async def test_stamp_labels_only_successful_files_owned_by_the_caller(monkeypatch):
    fake = _FakeOpenSearch({"f1": {"query_data": _query_data()}})
    _install(monkeypatch, fake)
    ok = _file("a", TaskStatus.COMPLETED, document_id="doc-a")
    dup = _file("b", TaskStatus.SKIPPED, document_id="doc-b")
    failed = _file("c", TaskStatus.FAILED, document_id="doc-c")
    no_doc = _file("d", TaskStatus.SKIPPED, document_id=None)

    await apply_collection_labels(_task(ok, dup, failed, no_doc), "user-1")

    stamped = [
        call["body"]["query"]["bool"]["filter"][0]["term"]["document_id"]
        for call in fake.update_by_query_calls
    ]
    assert stamped == ["doc-a", "doc-b"]
    call = fake.update_by_query_calls[0]
    assert call["index"] == "documents"
    assert call["refresh"] is True
    assert call["body"]["query"]["bool"]["filter"][1] == {"term": {"owner": "user-1"}}
    assert call["body"]["script"]["params"]["labels"] == ["collection:f1"]
    assert ok.collection_labels_applied and dup.collection_labels_applied
    assert not failed.collection_labels_applied


@pytest.mark.asyncio
async def test_first_membership_write_adds_the_labels_condition_once(monkeypatch):
    fake = _FakeOpenSearch({"f1": {"query_data": _query_data()}})
    _install(monkeypatch, fake)

    await apply_collection_labels(
        _task(
            _file("a", TaskStatus.COMPLETED, document_id="doc-a"),
            _file("b", TaskStatus.COMPLETED, document_id="doc-b"),
        ),
        "user-1",
    )
    await apply_collection_labels(
        _task(_file("c", TaskStatus.COMPLETED, document_id="doc-c")), "user-1"
    )

    assert [fid for fid, _ in fake.filter_updates] == ["f1"]
    saved = json.loads(fake.filters["f1"]["query_data"])
    assert saved["filters"] == {"data_sources": ["*"], "labels": ["collection:f1"]}
    assert saved["limit"] == 10


@pytest.mark.asyncio
async def test_deleted_filter_is_skipped_and_others_still_apply(monkeypatch):
    fake = _FakeOpenSearch({"f2": {"query_data": _query_data()}})
    _install(monkeypatch, fake)
    warn = Mock()
    monkeypatch.setattr(collection_membership.logger, "warning", warn)

    ft = _file("a", TaskStatus.COMPLETED, document_id="doc-a", filter_ids=("gone", "f2"))
    await apply_collection_labels(_task(ft), "user-1")

    assert fake.update_by_query_calls[0]["body"]["script"]["params"]["labels"] == ["collection:f2"]
    assert [fid for fid, _ in fake.filter_updates] == ["f2"]
    assert any(c.kwargs.get("filter_id") == "gone" for c in warn.call_args_list)


@pytest.mark.asyncio
async def test_only_deleted_filters_means_no_write(monkeypatch):
    fake = _FakeOpenSearch({})
    _install(monkeypatch, fake)

    await apply_collection_labels(_task(_file("a", TaskStatus.COMPLETED)), "user-1")

    assert fake.update_by_query_calls == []
    assert fake.filter_updates == []


@pytest.mark.asyncio
async def test_failed_label_write_leaves_file_completed_with_a_warning(monkeypatch):
    fake = _FakeOpenSearch({"f1": {"query_data": _query_data()}})
    fake.update_by_query = AsyncMock(side_effect=RuntimeError("boom"))
    _install(monkeypatch, fake)
    ft = _file("a", TaskStatus.COMPLETED, document_id="doc-a")

    await apply_collection_labels(_task(ft), "user-1")

    assert ft.status == TaskStatus.COMPLETED
    assert "collection_warning" in ft.result
    assert not ft.collection_labels_applied
    assert fake.filter_updates == []


@pytest.mark.asyncio
async def test_files_without_filter_ids_cost_nothing(monkeypatch):
    fake = _FakeOpenSearch({})
    _install(monkeypatch, fake)

    await apply_collection_labels(_task(_file("a", TaskStatus.COMPLETED, filter_ids=())), "user-1")

    assert fake.update_by_query_calls == []


def test_anonymous_user_also_owns_ownerless_chunks():
    query = build_own_document_chunks_query("doc-a", "anonymous")
    owner_clause = query["bool"]["filter"][1]
    assert {"term": {"owner": "anonymous"}} in owner_clause["bool"]["should"]
    assert {"bool": {"must_not": {"exists": {"field": "owner"}}}} in owner_clause["bool"]["should"]


@pytest.mark.asyncio
async def test_wildcard_label_is_replaced_by_the_collection_label(monkeypatch):
    fake = _FakeOpenSearch(
        {"f1": {"query_data": _query_data({"data_sources": ["*"], "labels": ["*", "team:a"]})}}
    )
    _install(monkeypatch, fake)

    await apply_collection_labels(_task(_file("a", TaskStatus.COMPLETED)), "user-1")

    saved = json.loads(fake.filters["f1"]["query_data"])
    assert saved["filters"]["labels"] == ["team:a", "collection:f1"]
    assert _strip_wildcards(saved["filters"])["labels"] == ["team:a", "collection:f1"]


@pytest.mark.asyncio
async def test_condition_write_keeps_an_edit_made_since_the_read(monkeypatch):
    fake = _FakeOpenSearch({"f1": {"name": "old", "query_data": _query_data()}})
    _install(monkeypatch, fake)
    renamed = json.dumps({"filters": {"data_sources": ["*"]}, "limit": 25})
    fake.before_write = lambda: fake.edit("f1", name="new", query_data=renamed)

    await apply_collection_labels(_task(_file("a", TaskStatus.COMPLETED)), "user-1")

    saved = json.loads(fake.filters["f1"]["query_data"])
    assert fake.filters["f1"]["name"] == "new"
    assert saved["limit"] == 25
    assert saved["filters"]["labels"] == ["collection:f1"]


@pytest.mark.asyncio
async def test_version_conflicted_chunks_are_retried(monkeypatch):
    fake = _FakeOpenSearch(
        {"f1": {"query_data": _query_data()}},
        ubq_responses=[{"updated": 2, "version_conflicts": 1, "failures": []}],
    )
    _install(monkeypatch, fake)
    ft = _file("a", TaskStatus.COMPLETED, document_id="doc-a")

    await apply_collection_labels(_task(ft), "user-1")

    assert len(fake.update_by_query_calls) == 2
    assert ft.collection_labels_applied
    assert [fid for fid, _ in fake.filter_updates] == ["f1"]


@pytest.mark.asyncio
async def test_persistent_conflicts_leave_file_unlabeled_and_filter_unchanged(monkeypatch):
    conflicted = {"updated": 0, "version_conflicts": 1, "failures": []}
    fake = _FakeOpenSearch({"f1": {"query_data": _query_data()}}, ubq_responses=[conflicted] * 3)
    _install(monkeypatch, fake)
    ft = _file("a", TaskStatus.COMPLETED, document_id="doc-a")

    await apply_collection_labels(_task(ft), "user-1")

    assert len(fake.update_by_query_calls) == 3
    assert not ft.collection_labels_applied
    assert "collection_warning" in ft.result
    assert fake.filter_updates == []


@pytest.mark.asyncio
async def test_failed_condition_write_leaves_file_retryable_until_it_succeeds(monkeypatch):
    fake = _FakeOpenSearch({"f1": {"name": "old", "query_data": _query_data()}})
    _install(monkeypatch, fake)
    working_update = fake.update
    fake.update = AsyncMock(side_effect=RuntimeError("boom"))
    ft = _file("a", TaskStatus.COMPLETED, document_id="doc-a")
    task = _task(ft)

    await apply_collection_labels(task, "user-1")

    assert ft.status == TaskStatus.COMPLETED
    assert not ft.collection_labels_applied
    assert "collection_warning" in ft.result
    assert fake.filter_updates == []

    # The retry reloads the filter and merges into whatever is there now.
    fake.update = working_update
    renamed = json.dumps({"filters": {"data_sources": ["*"]}, "limit": 25})
    fake.edit("f1", name="new", query_data=renamed)

    await apply_collection_labels(task, "user-1")

    assert ft.collection_labels_applied
    assert "collection_warning" not in ft.result
    saved = json.loads(fake.filters["f1"]["query_data"])
    assert fake.filters["f1"]["name"] == "new"
    assert saved["limit"] == 25
    assert saved["filters"]["labels"] == ["collection:f1"]


# --- task completion order ---------------------------------------------------


@pytest.mark.asyncio
async def test_task_reports_completed_only_after_labels_are_written(monkeypatch):
    from services.task_service import TaskService

    monkeypatch.setattr("config.settings.clients", SimpleNamespace(opensearch=MagicMock()))
    monkeypatch.setattr(
        "config.settings.clients.opensearch.indices.refresh", AsyncMock(), raising=False
    )
    status_at_stamp: list[TaskStatus] = []

    async def fake_apply(upload_task, user_id):
        status_at_stamp.append(upload_task.status)
        assert user_id == "user1"

    monkeypatch.setattr(collection_membership, "apply_collection_labels", fake_apply)

    class _Processor:
        async def process_item(self, upload_task, item, file_task):
            file_task.status = TaskStatus.COMPLETED
            file_task.document_id = "doc-a"
            upload_task.successful_files += 1

    service = TaskService(document_service=Mock(), ingestion_timeout=2)
    task = UploadTask(
        task_id="t1",
        total_files=1,
        file_tasks={"/a": FileTask(file_path="/a", filename="a", filter_ids=("f1",))},
        processor=_Processor(),
    )
    service.task_store.setdefault("user1", {})["t1"] = task

    await service.background_custom_processor("user1", "t1", ["/a"])

    assert status_at_stamp == [TaskStatus.RUNNING]
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_create_custom_task_carries_filter_ids_onto_each_file(monkeypatch):
    from services.task_service import TaskService

    service = TaskService(document_service=Mock(), ingestion_timeout=2)
    monkeypatch.setattr(service, "background_custom_processor", AsyncMock())

    task_id = await service.create_custom_task(
        "user1", ["/a", "/b"], processor=Mock(), filter_ids=["f1", "f2"]
    )

    task = service.task_store["user1"][task_id]
    assert {ft.filter_ids for ft in task.file_tasks.values()} == {("f1", "f2")}


@pytest.mark.asyncio
async def test_task_appended_to_while_labeling_stays_running(monkeypatch):
    from services.task_service import TaskService

    monkeypatch.setattr("config.settings.clients", SimpleNamespace(opensearch=MagicMock()))
    monkeypatch.setattr(
        "config.settings.clients.opensearch.indices.refresh", AsyncMock(), raising=False
    )

    async def append_a_batch(upload_task, user_id):
        # Another upload joins this task (existing_task_id) mid-finalize.
        upload_task.file_tasks["/b"] = FileTask(file_path="/b", filename="b")
        upload_task.total_files += 1

    monkeypatch.setattr(collection_membership, "apply_collection_labels", append_a_batch)

    class _Processor:
        async def process_item(self, upload_task, item, file_task):
            file_task.status = TaskStatus.COMPLETED
            upload_task.successful_files += 1

    service = TaskService(document_service=Mock(), ingestion_timeout=2)
    task = UploadTask(
        task_id="t1",
        total_files=1,
        file_tasks={"/a": FileTask(file_path="/a", filename="a")},
        processor=_Processor(),
    )
    service.task_store.setdefault("user1", {})["t1"] = task

    await service.background_custom_processor("user1", "t1", ["/a"])

    assert task.status == TaskStatus.RUNNING


# --- scoped search -----------------------------------------------------------


def test_saved_filter_keeps_its_labels_condition_through_normalization():
    normalized = json.loads(
        normalize_query_data(
            {"filters": {"data_sources": ["*"], "labels": [collection_label("f1")]}}
        )
    )
    assert normalized["filters"]["labels"] == ["collection:f1"]


def test_filter_resolution_scopes_to_members():
    resolved = _strip_wildcards(
        {
            "data_sources": ["*"],
            "document_types": ["application/pdf"],
            "labels": ["collection:f1"],
        }
    )
    assert resolved == {"document_types": ["application/pdf"], "labels": ["collection:f1"]}


def test_search_and_chat_clauses_match_on_the_labels_field():
    filters = {"labels": ["collection:f1"]}
    assert {"term": {"labels": "collection:f1"}} in _build_search_filter_clauses(filters)
    assert {"term": {"labels": "collection:f1"}} in build_filter_clauses(filters)
