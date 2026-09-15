"""Regression tests for GitHub issue #2138.

_ensure_index_exists() raises RuntimeError when OPENRAG_SERVICE_TOKEN is
missing in saas/on_prem mode. upload_path and upload_bucket must turn that
into a controlled 5xx JSONResponse instead of an unhandled exception, and
must not create a task/processor when the check fails.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _json(response):
    return json.loads(response.body.decode())


def _make_user():
    return SimpleNamespace(user_id="alice", name="Alice", email="alice@example.com", jwt_token="token")


@pytest.mark.asyncio
async def test_upload_path_returns_5xx_and_skips_task_when_index_check_fails(monkeypatch, tmp_path):
    from api import documents as documents_api
    from api import upload as upload_api

    (tmp_path / "doc.txt").write_text("hello")

    monkeypatch.setattr(
        documents_api,
        "_ensure_index_exists",
        AsyncMock(side_effect=RuntimeError(
            "OPENRAG_SERVICE_TOKEN is required for the index-admin OpenSearch client in saas mode."
        )),
    )

    task_service = MagicMock()
    task_service.create_upload_task = AsyncMock(return_value="task-should-not-run")

    response = await upload_api.upload_path(
        upload_api.UploadPathBody(path=str(tmp_path)),
        task_service=task_service,
        session_manager=MagicMock(),
        user=_make_user(),
    )

    assert 500 <= response.status_code < 600
    body = _json(response)
    assert "OPENRAG_SERVICE_TOKEN" in body["error"]
    task_service.create_upload_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_bucket_returns_5xx_and_skips_task_when_index_check_fails(monkeypatch):
    from api import documents as documents_api
    from api import upload as upload_api

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")

    monkeypatch.setattr(
        documents_api,
        "_ensure_index_exists",
        AsyncMock(side_effect=RuntimeError(
            "OPENRAG_SERVICE_TOKEN is required for the index-admin OpenSearch client in saas mode."
        )),
    )

    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{"Contents": [{"Key": "file1.txt"}]}]
    fake_s3_client = MagicMock()
    fake_s3_client.get_paginator.return_value = fake_paginator
    monkeypatch.setattr(upload_api.boto3, "client", MagicMock(return_value=fake_s3_client))

    task_service = MagicMock()
    task_service.create_custom_task = AsyncMock(return_value="task-should-not-run")

    response = await upload_api.upload_bucket(
        upload_api.UploadBucketBody(s3_url="s3://my-bucket/prefix"),
        task_service=task_service,
        models_service=MagicMock(),
        docling_service=MagicMock(),
        session_manager=MagicMock(),
        user=_make_user(),
    )

    assert 500 <= response.status_code < 600
    body = _json(response)
    assert "OPENRAG_SERVICE_TOKEN" in body["error"]
    task_service.create_custom_task.assert_not_awaited()
