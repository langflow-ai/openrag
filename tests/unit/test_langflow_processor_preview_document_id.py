"""Regression tests for preview index-proof document_id threading."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from utils.hash_utils import hash_id


@pytest.mark.asyncio
async def test_langflow_processor_threads_document_id_for_index_proof(tmp_path):
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=AsyncMock())

    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="user-1",
        jwt_token="Bearer user-token",
    )
    processor.check_filename_exists = AsyncMock(side_effect=[False, True])

    item = tmp_path / "report.pdf"
    item.write_bytes(b"%PDF-1.4 dummy")

    file_task = FileTask(file_path=str(item))
    file_task.filename = "My Report.pdf"
    upload_task = UploadTask(task_id="task-1", total_files=1)

    await processor.process_item(upload_task, str(item), file_task)

    expected_id = hash_id(str(item))
    assert file_task.status == TaskStatus.COMPLETED
    assert file_task.document_id == expected_id
    call_kwargs = langflow_file_service.upload_and_ingest_file.await_args.kwargs
    assert call_kwargs["document_id"] == expected_id
