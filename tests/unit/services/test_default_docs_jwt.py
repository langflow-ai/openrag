import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.default_docs_service import (  # noqa: E402
    _ingest_default_documents_langflow,
    _ingest_default_documents_url_langflow,
    ingest_default_documents_when_ready,
)


class FakeSessionManager:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def get_effective_jwt_token(self, user_id: str, jwt_token: str | None) -> str:
        self.calls.append((user_id, jwt_token))
        return "Bearer default-doc-token"


class FakeTaskService:
    def __init__(self):
        self.upload_kwargs = None
        self.url_kwargs = None

    async def create_langflow_upload_task(self, **kwargs):
        self.upload_kwargs = kwargs
        return "upload-task"

    async def create_langflow_url_upload_task(self, **kwargs):
        self.url_kwargs = kwargs
        return "url-task"


@pytest.mark.asyncio
async def test_default_file_docs_use_effective_jwt_helper():
    session_manager = FakeSessionManager()
    task_service = FakeTaskService()

    task_id = await _ingest_default_documents_langflow(
        langflow_file_service=object(),
        session_manager=session_manager,
        task_service=task_service,
        file_paths=["/tmp/openrag-doc.md"],
    )

    assert task_id == "upload-task"
    assert session_manager.calls == [("anonymous", None)]
    assert task_service.upload_kwargs["jwt_token"] == "Bearer default-doc-token"


@pytest.mark.asyncio
async def test_default_url_docs_use_effective_jwt_helper():
    session_manager = FakeSessionManager()
    task_service = FakeTaskService()

    task_id = await _ingest_default_documents_url_langflow(
        langflow_file_service=object(),
        session_manager=session_manager,
        task_service=task_service,
        docs_url="https://docs.example.test",
        crawl_depth=1,
    )

    assert task_id == "url-task"
    assert session_manager.calls == [("anonymous", None)]
    assert task_service.url_kwargs["jwt_token"] == "Bearer default-doc-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("disable_langflow", "local_helper_name"),
    [
        (True, "_ingest_default_documents_openrag"),
        (False, "_ingest_default_documents_langflow"),
    ],
)
async def test_local_default_docs_get_separate_task_from_url_ingest(
    tmp_path, disable_langflow, local_helper_name
):
    local_doc = tmp_path / "local.md"
    local_doc.write_text("local default documentation")
    config = SimpleNamespace(
        knowledge=SimpleNamespace(disable_ingest_with_langflow=disable_langflow)
    )
    local_helper = AsyncMock(return_value="local-task")

    with (
        patch(
            "services.default_docs_service.get_openrag_config",
            return_value=config,
        ),
        patch(
            "services.default_docs_service.ingest_openrag_docs_when_ready",
            new=AsyncMock(return_value="url-task"),
        ),
        patch("services.default_docs_service._get_documents_dir", return_value=str(tmp_path)),
        patch(
            f"services.default_docs_service.{local_helper_name}",
            new=local_helper,
        ),
        patch(
            "services.default_docs_service.TelemetryClient.send_event",
            new=AsyncMock(),
        ),
    ):
        task_id = await ingest_default_documents_when_ready(
            document_service=object(),
            models_service=object(),
            task_service=object(),
            langflow_file_service=object(),
            session_manager=object(),
        )

    assert task_id == "local-task"
    assert local_helper.await_args.kwargs.get("existing_task_id") is None
