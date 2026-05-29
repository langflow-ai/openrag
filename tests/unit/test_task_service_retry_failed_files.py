"""Unit tests for TaskService.retry_failed_files."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from models.tasks import DoclingPhaseStatus, FileTask, IngestionPhase, TaskStatus, UploadTask
from services.task_service import TaskService


@pytest.fixture
def task_service():
    return TaskService(document_service=Mock(), ingestion_timeout=2)


def _retryable_failed_file(
    file_path: str = "/data/doc.pdf",
    *,
    error: str = "Docling conversion did not complete (timeout)",
) -> FileTask:
    ft = FileTask(file_path=file_path, filename="doc.pdf")
    ft.status = TaskStatus.FAILED
    ft.phase = IngestionPhase.DOCLING
    ft.docling_status = DoclingPhaseStatus.FAILED
    ft.error = error
    return ft


def _store_task(
    task_service: TaskService,
    user_id: str,
    upload_task: UploadTask,
) -> None:
    task_service.task_store.setdefault(user_id, {})[upload_task.task_id] = upload_task


@pytest.mark.asyncio
async def test_retry_all_failed_retryable_files(task_service):
    processor = Mock()
    ft_a = _retryable_failed_file("/data/a.pdf")
    ft_b = _retryable_failed_file("/data/b.pdf")
    task = UploadTask(
        task_id="task-1",
        total_files=2,
        file_tasks={"/data/a.pdf": ft_a, "/data/b.pdf": ft_b},
        status=TaskStatus.FAILED,
        failed_files=2,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    with (
        patch("os.path.isfile", return_value=True),
        patch.object(
            task_service,
            "background_custom_processor",
            new_callable=AsyncMock,
        ) as mock_bg,
        patch("asyncio.create_task", return_value=Mock()),
    ):
        result = await task_service.retry_failed_files("user1", "task-1")

    assert result is not None
    assert result["retried"] == 2
    assert result["status"] == "accepted"
    assert ft_a.status == TaskStatus.PENDING
    assert ft_b.status == TaskStatus.PENDING
    mock_bg.assert_called_once()
    assert set(mock_bg.call_args[0][2]) == {"/data/a.pdf", "/data/b.pdf"}


@pytest.mark.asyncio
async def test_retry_subset_by_file_paths(task_service):
    processor = Mock()
    ft_a = _retryable_failed_file("/data/a.pdf")
    ft_b = _retryable_failed_file("/data/b.pdf")
    task = UploadTask(
        task_id="task-1",
        total_files=2,
        file_tasks={"/data/a.pdf": ft_a, "/data/b.pdf": ft_b},
        status=TaskStatus.FAILED,
        failed_files=2,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    with (
        patch("os.path.isfile", return_value=True),
        patch.object(
            task_service,
            "background_custom_processor",
            new_callable=AsyncMock,
        ) as mock_bg,
        patch("asyncio.create_task", return_value=Mock()),
    ):
        result = await task_service.retry_failed_files(
            "user1",
            "task-1",
            file_paths=["/data/a.pdf"],
        )

    assert result is not None
    assert result["retried"] == 1
    assert ft_a.status == TaskStatus.PENDING
    assert ft_b.status == TaskStatus.FAILED
    mock_bg.assert_called_once()
    assert mock_bg.call_args[0][2] == ["/data/a.pdf"]


@pytest.mark.asyncio
async def test_retry_unknown_path_is_skipped(task_service):
    processor = Mock()
    ft_a = _retryable_failed_file("/data/a.pdf")
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"/data/a.pdf": ft_a},
        status=TaskStatus.FAILED,
        failed_files=1,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    with patch("os.path.isfile", return_value=True):
        result = await task_service.retry_failed_files(
            "user1",
            "task-1",
            file_paths=["/data/missing.pdf"],
        )

    assert result is not None
    assert result["retried"] == 0
    assert result["status"] == "no_op"
    assert result["skipped"] == [{"file_path": "/data/missing.pdf", "reason": "file_not_in_task"}]
    assert ft_a.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_retry_connector_connectivity_error_is_retryable(task_service):
    processor = Mock()
    ft = FileTask(file_path="/data/connector.pdf", filename="connector.pdf")
    ft.status = TaskStatus.FAILED
    ft.phase = IngestionPhase.DOCLING
    ft.docling_status = DoclingPhaseStatus.PENDING
    ft.error = "All connection attempts failed"
    task = UploadTask(
        task_id="task-connector",
        total_files=1,
        file_tasks={"/data/connector.pdf": ft},
        status=TaskStatus.FAILED,
        failed_files=1,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    with (
        patch("os.path.isfile", return_value=True),
        patch.object(
            task_service,
            "background_custom_processor",
            new_callable=AsyncMock,
        ) as mock_bg,
        patch("asyncio.create_task", return_value=Mock()),
    ):
        result = await task_service.retry_failed_files("user1", "task-connector")

    assert result is not None
    assert result["retried"] == 1
    assert result["status"] == "accepted"
    assert ft.status == TaskStatus.PENDING
    mock_bg.assert_called_once()


@pytest.mark.asyncio
async def test_langflow_disconnect_error_is_retryable(task_service):
    processor = Mock()
    ft = FileTask(file_path="google-drive-file-id", filename="statement.pdf")
    ft.status = TaskStatus.FAILED
    ft.phase = IngestionPhase.DOCLING
    ft.docling_status = DoclingPhaseStatus.PENDING
    ft.error = "Server disconnected without sending a response."
    task = UploadTask(
        task_id="task-langflow-disconnect",
        total_files=1,
        file_tasks={"google-drive-file-id": ft},
        status=TaskStatus.FAILED,
        failed_files=1,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    metadata = task_service._infer_failure_metadata(ft)
    assert metadata is not None
    assert metadata["actionable_by"] == "RETRYABLE"
    assert metadata["component"] == "langflow"

    with (
        patch("os.path.isfile", return_value=False),
        patch.object(
            task_service,
            "background_custom_processor",
            new_callable=AsyncMock,
        ) as mock_bg,
        patch("asyncio.create_task", return_value=Mock()),
    ):
        result = await task_service.retry_failed_files("user1", "task-langflow-disconnect")

    assert result is not None
    assert result["retried"] == 1
    assert ft.phase == IngestionPhase.LANGFLOW
    mock_bg.assert_called_once()


@pytest.mark.asyncio
async def test_retry_connector_id_path_does_not_require_local_file(task_service):
    processor = Mock()
    ft = FileTask(file_path="remote-file-id-123", filename="connector.pdf")
    ft.status = TaskStatus.FAILED
    ft.phase = IngestionPhase.DOCLING
    ft.docling_status = DoclingPhaseStatus.PENDING
    ft.error = "All connection attempts failed"
    task = UploadTask(
        task_id="task-connector-id",
        total_files=1,
        file_tasks={"remote-file-id-123": ft},
        status=TaskStatus.FAILED,
        failed_files=1,
        processor=processor,
    )
    _store_task(task_service, "user1", task)

    with (
        patch("os.path.isfile", return_value=False),
        patch.object(
            task_service,
            "background_custom_processor",
            new_callable=AsyncMock,
        ) as mock_bg,
        patch("asyncio.create_task", return_value=Mock()),
    ):
        result = await task_service.retry_failed_files("user1", "task-connector-id")

    assert result is not None
    assert result["retried"] == 1
    assert result["status"] == "accepted"
    assert ft.status == TaskStatus.PENDING
    mock_bg.assert_called_once()


def test_is_retryable_local_upload_temp_true_for_failed_local_timeout(task_service):
    temp_path = "/var/folders/tmp/retryable.tmp"
    ft = _retryable_failed_file(temp_path)
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={temp_path: ft},
        temp_file_paths=[temp_path],
    )

    assert task_service._is_retryable_local_upload_temp(task, temp_path) is True


def test_is_retryable_local_upload_temp_resolves_file_task_by_file_path(task_service):
    temp_path = "/var/folders/tmp/retryable.tmp"
    ft = _retryable_failed_file(temp_path)
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={"different-key": ft},
        temp_file_paths=[temp_path],
    )

    assert task_service._is_retryable_local_upload_temp(task, temp_path) is True


def test_is_retryable_local_upload_temp_false_for_connector_id(task_service):
    file_path = "google-drive-file-id"
    ft = FileTask(file_path=file_path, filename="doc.pdf")
    ft.status = TaskStatus.FAILED
    ft.error = "All connection attempts failed"
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={file_path: ft},
        temp_file_paths=[],
    )

    assert task_service._is_retryable_local_upload_temp(task, file_path) is False


def test_cleanup_upload_temp_files_keeps_retryable_local_failure(task_service):
    retryable_path = "/var/folders/tmp/retryable.tmp"
    other_path = "/var/folders/tmp/success.tmp"
    ft_retryable = _retryable_failed_file(retryable_path)
    ft_success = FileTask(file_path=other_path, filename="ok.pdf")
    ft_success.status = TaskStatus.COMPLETED
    task = UploadTask(
        task_id="task-1",
        total_files=2,
        file_tasks={retryable_path: ft_retryable, other_path: ft_success},
        temp_file_paths=[retryable_path, other_path],
    )

    with (
        patch("utils.file_utils.safe_unlink") as mock_unlink,
        patch("os.path.exists", return_value=False),
    ):
        task_service._cleanup_upload_temp_files(task)

    mock_unlink.assert_called_once_with(other_path)
    assert task.temp_file_paths == [retryable_path]


def test_cleanup_upload_temp_files_removes_non_retryable_failure(task_service):
    temp_path = "/var/folders/tmp/corrupt.tmp"
    ft = FileTask(file_path=temp_path, filename="bad.pdf")
    ft.status = TaskStatus.FAILED
    ft.error = "The file appears corrupted or invalid"
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={temp_path: ft},
        temp_file_paths=[temp_path],
    )

    with (
        patch("utils.file_utils.safe_unlink") as mock_unlink,
        patch("os.path.exists", return_value=False),
    ):
        task_service._cleanup_upload_temp_files(task)

    mock_unlink.assert_called_once_with(temp_path)
    assert task.temp_file_paths == []


def test_cleanup_upload_temp_files_retains_path_when_unlink_fails(task_service):
    temp_path = "/var/folders/tmp/still-there.tmp"
    ft = FileTask(file_path=temp_path, filename="ok.pdf")
    ft.status = TaskStatus.COMPLETED
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={temp_path: ft},
        temp_file_paths=[temp_path],
    )

    with (
        patch("utils.file_utils.safe_unlink") as mock_unlink,
        patch("os.path.exists", return_value=True),
    ):
        task_service._cleanup_upload_temp_files(task)

    mock_unlink.assert_called_once_with(temp_path)
    assert task.temp_file_paths == [temp_path]


def test_cleanup_upload_temp_files_does_not_unlink_retryable_local_failure(task_service):
    retryable_path = "/var/folders/tmp/retryable.tmp"
    ft = _retryable_failed_file(retryable_path)
    task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={retryable_path: ft},
        temp_file_paths=[retryable_path],
    )

    with patch("utils.file_utils.safe_unlink") as mock_unlink:
        task_service._cleanup_upload_temp_files(task)

    mock_unlink.assert_not_called()
    assert task.temp_file_paths == [retryable_path]


def test_cleanup_upload_temp_files_retains_unmapped_absolute_temp(task_service):
    temp_path = "/var/folders/tmp/unmapped.tmp"
    task = UploadTask(
        task_id="task-1",
        total_files=0,
        file_tasks={},
        temp_file_paths=[temp_path],
    )

    with patch("utils.file_utils.safe_unlink") as mock_unlink:
        task_service._cleanup_upload_temp_files(task)

    mock_unlink.assert_not_called()
    assert task.temp_file_paths == [temp_path]
