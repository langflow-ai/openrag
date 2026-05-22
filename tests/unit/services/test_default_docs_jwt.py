import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.default_docs_service import (  # noqa: E402
    _ingest_default_documents_langflow,
    _ingest_default_documents_url_langflow,
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
