"""
Unit tests for TaskService.get_task_status2 and its supporting helpers.

Tests verify that:
- Failed file entries receive structured failure metadata (component,
  failure_phase, user_facing_message, actionable_by) when the cause is known.
- Non-failed entries (completed, running, pending) are never decorated.
- Unknown failures produce no extra fields.
- get_task_status (the existing method) is unaffected by the refactor.
"""

from unittest.mock import Mock

import pytest

from models.tasks import DoclingPhaseStatus, FileTask, IngestionPhase, TaskStatus, UploadTask
from services.task_service import TaskService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def task_service():
    return TaskService(document_service=Mock(), ingestion_timeout=2)


def _make_upload_task(task_id: str, file_tasks: dict[str, FileTask]) -> UploadTask:
    return UploadTask(task_id=task_id, total_files=len(file_tasks), file_tasks=file_tasks)


def _make_file_task(
    *,
    file_path: str = "test.pdf",
    status: TaskStatus = TaskStatus.FAILED,
    phase: IngestionPhase = IngestionPhase.DOCLING,
    docling_status: DoclingPhaseStatus = DoclingPhaseStatus.PENDING,
    error: str | None = None,
    filename: str | None = "test.pdf",
) -> FileTask:
    ft = FileTask(file_path=file_path, filename=filename)
    ft.status = status
    ft.phase = phase
    ft.docling_status = docling_status
    ft.error = error
    return ft


def _store_task(task_service: TaskService, user_id: str, upload_task: UploadTask) -> None:
    task_service.task_store.setdefault(user_id, {})[upload_task.task_id] = upload_task


# ---------------------------------------------------------------------------
# _infer_failure_metadata
# ---------------------------------------------------------------------------


class TestInferFailureMetadata:
    def test_docling_failed_status(self, task_service):
        ft = _make_file_task(docling_status=DoclingPhaseStatus.FAILED)
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "docling"
        assert meta["failure_phase"] == "parsing"
        assert meta["actionable_by"] == "USER_ACTIONABLE"
        assert meta["user_facing_message"]

    def test_docling_expired_status(self, task_service):
        ft = _make_file_task(docling_status=DoclingPhaseStatus.EXPIRED)
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "docling"
        assert meta["failure_phase"] == "parsing"
        assert meta["actionable_by"] == "RETRYABLE"
        assert meta["user_facing_message"]

    def test_docling_timeout_via_error_string(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error="Docling conversion did not complete (timeout): polling exceeded 300s",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "docling"
        assert meta["failure_phase"] == "parsing"
        assert meta["actionable_by"] == "RETRYABLE"

    def test_docling_phase_still_processing(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PROCESSING,
            error="some generic failure",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "docling"
        assert meta["failure_phase"] == "parsing"
        assert meta["actionable_by"] == "RETRYABLE"

    def test_langflow_phase_failure(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.LANGFLOW,
            docling_status=DoclingPhaseStatus.SUCCESS,
            error="Langflow run timed out",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "langflow"
        assert meta["failure_phase"] == "unknown"
        assert meta["actionable_by"] == "RETRYABLE"

    def test_duplicate_file_error(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error="File with name 'report.pdf' already exists",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "openrag"
        assert meta["failure_phase"] == "file_validation"
        assert meta["actionable_by"] == "USER_ACTIONABLE"

    def test_langflow_duplicate_file_error_prefers_file_validation(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.LANGFLOW,
            docling_status=DoclingPhaseStatus.SUCCESS,
            error="File with name 'report.pdf' already exists",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is not None
        assert meta["component"] == "openrag"
        assert meta["failure_phase"] == "file_validation"
        assert meta["actionable_by"] == "USER_ACTIONABLE"

    def test_unknown_failure_returns_none(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error="some completely unknown error",
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is None

    def test_no_error_string_unknown_phase(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error=None,
        )
        meta = task_service._infer_failure_metadata(ft)
        assert meta is None


# ---------------------------------------------------------------------------
# get_task_status2 — task not found
# ---------------------------------------------------------------------------


class TestGetTaskStatus2NotFound:
    def test_missing_task_id_returns_none(self, task_service):
        assert task_service.get_task_status2("user1", "") is None

    def test_unknown_task_id_returns_none(self, task_service):
        assert task_service.get_task_status2("user1", "does-not-exist") is None


# ---------------------------------------------------------------------------
# get_task_status2 — failure metadata on failed files
# ---------------------------------------------------------------------------


class TestGetTaskStatus2FailureMetadata:
    def test_docling_failed_adds_metadata(self, task_service):
        ft = _make_file_task(
            docling_status=DoclingPhaseStatus.FAILED,
            error="Docling conversion did not complete (failed): Docling reported failure",
        )
        task = _make_upload_task("t1", {"test.pdf": ft})
        task.status = TaskStatus.FAILED
        task.failed_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t1")
        file_entry = result["files"]["test.pdf"]

        assert file_entry["status"] == "failed"
        assert file_entry["component"] == "docling"
        assert file_entry["failure_phase"] == "parsing"
        assert file_entry["actionable_by"] == "USER_ACTIONABLE"
        assert file_entry["user_facing_message"]

    def test_docling_expired_adds_metadata(self, task_service):
        ft = _make_file_task(docling_status=DoclingPhaseStatus.EXPIRED)
        task = _make_upload_task("t2", {"test.pdf": ft})
        task.status = TaskStatus.FAILED
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t2")
        file_entry = result["files"]["test.pdf"]

        assert file_entry["component"] == "docling"
        assert file_entry["failure_phase"] == "parsing"
        assert file_entry["actionable_by"] == "RETRYABLE"

    def test_langflow_failure_adds_metadata(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.LANGFLOW,
            docling_status=DoclingPhaseStatus.SUCCESS,
            error="Langflow run failed",
        )
        task = _make_upload_task("t3", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t3")
        file_entry = result["files"]["doc.pdf"]

        assert file_entry["component"] == "langflow"
        assert file_entry["failure_phase"] == "unknown"
        assert file_entry["actionable_by"] == "RETRYABLE"

    def test_duplicate_file_failure_adds_metadata(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error="File with name 'report.pdf' already exists",
        )
        task = _make_upload_task("t4", {"report.pdf": ft})
        task.status = TaskStatus.FAILED
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t4")
        file_entry = result["files"]["report.pdf"]

        assert file_entry["component"] == "openrag"
        assert file_entry["failure_phase"] == "file_validation"
        assert file_entry["actionable_by"] == "USER_ACTIONABLE"

    def test_unknown_failure_adds_no_metadata_fields(self, task_service):
        ft = _make_file_task(
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PENDING,
            error="some unrecognised error",
        )
        task = _make_upload_task("t5", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t5")
        file_entry = result["files"]["doc.pdf"]

        assert "component" not in file_entry
        assert "failure_phase" not in file_entry
        assert "user_facing_message" not in file_entry
        assert "actionable_by" not in file_entry


# ---------------------------------------------------------------------------
# get_task_status2 — non-failed files get no metadata
# ---------------------------------------------------------------------------


class TestGetTaskStatus2NonFailedFiles:
    def test_completed_file_has_no_metadata(self, task_service):
        ft = _make_file_task(status=TaskStatus.COMPLETED, phase=IngestionPhase.COMPLETE)
        ft.docling_status = DoclingPhaseStatus.SUCCESS
        ft.error = None
        task = _make_upload_task("t6", {"doc.pdf": ft})
        task.status = TaskStatus.COMPLETED
        task.successful_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t6")
        file_entry = result["files"]["doc.pdf"]

        assert "component" not in file_entry
        assert "failure_phase" not in file_entry
        assert "user_facing_message" not in file_entry
        assert "actionable_by" not in file_entry

    def test_running_file_has_no_metadata(self, task_service):
        ft = _make_file_task(
            status=TaskStatus.RUNNING,
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PROCESSING,
            error=None,
        )
        task = _make_upload_task("t7", {"doc.pdf": ft})
        task.status = TaskStatus.RUNNING
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t7")
        file_entry = result["files"]["doc.pdf"]

        assert "component" not in file_entry
        assert "failure_phase" not in file_entry

    def test_pending_file_has_no_metadata(self, task_service):
        ft = _make_file_task(status=TaskStatus.PENDING, error=None)
        task = _make_upload_task("t8", {"doc.pdf": ft})
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t8")
        file_entry = result["files"]["doc.pdf"]

        assert "component" not in file_entry
        assert "failure_phase" not in file_entry


# ---------------------------------------------------------------------------
# get_task_status2 — mixed files
# ---------------------------------------------------------------------------


class TestGetTaskStatus2Mixed:
    def test_only_failed_files_get_metadata(self, task_service):
        failed_ft = _make_file_task(
            file_path="bad.pdf",
            filename="bad.pdf",
            docling_status=DoclingPhaseStatus.FAILED,
            error="Docling conversion did not complete (failed): Docling reported failure",
        )
        ok_ft = _make_file_task(
            file_path="good.pdf",
            filename="good.pdf",
            status=TaskStatus.COMPLETED,
            phase=IngestionPhase.COMPLETE,
            docling_status=DoclingPhaseStatus.SUCCESS,
            error=None,
        )
        running_ft = _make_file_task(
            file_path="wip.pdf",
            filename="wip.pdf",
            status=TaskStatus.RUNNING,
            phase=IngestionPhase.DOCLING,
            docling_status=DoclingPhaseStatus.PROCESSING,
            error=None,
        )
        task = _make_upload_task(
            "t9", {"bad.pdf": failed_ft, "good.pdf": ok_ft, "wip.pdf": running_ft}
        )
        task.status = TaskStatus.RUNNING
        task.successful_files = 1
        task.failed_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t9")

        bad = result["files"]["bad.pdf"]
        assert bad["component"] == "docling"
        assert bad["failure_phase"] == "parsing"

        good = result["files"]["good.pdf"]
        assert "component" not in good

        wip = result["files"]["wip.pdf"]
        assert "component" not in wip

    def test_top_level_fields_present(self, task_service):
        ft = _make_file_task(docling_status=DoclingPhaseStatus.FAILED)
        task = _make_upload_task("t10", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        task.failed_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status2("user1", "t10")

        for key in (
            "task_id",
            "status",
            "total_files",
            "processed_files",
            "successful_files",
            "failed_files",
            "running_files",
            "pending_files",
            "created_at",
            "updated_at",
            "duration_seconds",
            "files",
        ):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# get_task_status2 — anonymous user fallback
# ---------------------------------------------------------------------------


class TestGetTaskStatus2AnonymousFallback:
    def test_resolves_anonymous_task(self, task_service):
        from session_manager import AnonymousUser

        ft = _make_file_task(docling_status=DoclingPhaseStatus.FAILED)
        task = _make_upload_task("anon-task", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        anon_id = AnonymousUser().user_id
        task_service.task_store[anon_id] = {"anon-task": task}

        result = task_service.get_task_status2("some-other-user", "anon-task")
        assert result is not None
        assert result["task_id"] == "anon-task"
        assert result["files"]["doc.pdf"]["component"] == "docling"


# ---------------------------------------------------------------------------
# Regression: get_task_status remains unchanged
# ---------------------------------------------------------------------------


class TestGetTaskStatusRegression:
    def test_no_metadata_fields_in_original_method(self, task_service):
        ft = _make_file_task(
            docling_status=DoclingPhaseStatus.FAILED,
            error="Docling conversion did not complete (failed): Docling reported failure",
        )
        task = _make_upload_task("reg1", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        task.failed_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status("user1", "reg1")
        file_entry = result["files"]["doc.pdf"]

        assert file_entry["status"] == "failed"
        assert "component" not in file_entry
        assert "failure_phase" not in file_entry
        assert "user_facing_message" not in file_entry
        assert "actionable_by" not in file_entry

    def test_original_method_baseline_shape_unchanged(self, task_service):
        ft = _make_file_task(
            status=TaskStatus.COMPLETED,
            phase=IngestionPhase.COMPLETE,
            docling_status=DoclingPhaseStatus.SUCCESS,
            error=None,
        )
        task = _make_upload_task("reg2", {"doc.pdf": ft})
        task.status = TaskStatus.COMPLETED
        task.successful_files = 1
        _store_task(task_service, "user1", task)

        result = task_service.get_task_status("user1", "reg2")
        file_entry = result["files"]["doc.pdf"]

        expected_keys = {
            "status",
            "result",
            "error",
            "retry_count",
            "created_at",
            "updated_at",
            "duration_seconds",
            "filename",
            "phase",
            "docling_status",
            "docling_task_id",
        }
        assert set(file_entry.keys()) == expected_keys

    def test_both_methods_return_same_baseline_for_failed_file(self, task_service):
        """get_task_status2 must include all fields from get_task_status plus any extras."""
        ft = _make_file_task(
            docling_status=DoclingPhaseStatus.FAILED,
            error="Docling conversion did not complete (failed): Docling reported failure",
        )
        task = _make_upload_task("reg3", {"doc.pdf": ft})
        task.status = TaskStatus.FAILED
        task.failed_files = 1
        _store_task(task_service, "user1", task)

        v1 = task_service.get_task_status("user1", "reg3")
        v2 = task_service.get_task_status2("user1", "reg3")

        # All v1 top-level keys must appear in v2
        for key in v1:
            assert key in v2, f"get_task_status2 missing top-level key: {key}"
            if key != "files":
                assert v1[key] == v2[key], f"top-level key '{key}' differs"

        # All baseline file entry keys must survive in get_task_status2
        v1_file = v1["files"]["doc.pdf"]
        v2_file = v2["files"]["doc.pdf"]
        for key in v1_file:
            assert key in v2_file, f"get_task_status2 file entry missing key: {key}"
            assert v1_file[key] == v2_file[key], f"file entry key '{key}' differs"
