from unittest.mock import AsyncMock

import pytest

from connectors.url import api
from connectors.url.api import CreateSourceBody
from db.models.website_source import WebsitePage, WebsiteSource
from session_manager import User


def test_create_source_body_keeps_change_detection_outside_crawl_spec():
    body = CreateSourceBody(
        name="Documentation",
        starting_url="https://docs.example.com/",
        change_detection="always_reingest",
    )

    assert body.change_detection == "always_reingest"
    crawl_settings = body.spec().as_dict()
    assert crawl_settings["seed_url"] == "https://docs.example.com/"
    assert "change_detection" not in crawl_settings


def test_create_source_body_defaults_to_normalized_content_hash():
    body = CreateSourceBody(name="Documentation", starting_url="https://docs.example.com/")

    assert body.change_detection == "normalized_content_hash"


class _Session:
    def __init__(self, source: WebsiteSource, page: WebsitePage | None = None):
        self.source = source
        self.page = page
        self.commits = 0
        self.deleted: list[object] = []

    async def get(self, model, identifier):
        if model is WebsiteSource:
            return self.source if identifier == self.source.id else None
        if model is WebsitePage:
            return self.page if self.page and identifier == self.page.id else None
        return None

    async def commit(self):
        self.commits += 1

    async def delete(self, value):
        self.deleted.append(value)

    async def execute(self, _):
        return type("Result", (), {"scalar_one": lambda self: 1})()


@pytest.mark.asyncio
async def test_page_sync_enqueues_a_page_scoped_processor(monkeypatch):
    source = WebsiteSource(
        id="source-1",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        status="active",
    )
    page = WebsitePage(
        id="page-1",
        web_source_id=source.id,
        canonical_url="https://docs.example.com/guide",
        title="Guide",
        document_id="document-1",
        status="active",
    )
    enqueue = AsyncMock(return_value="task-1")
    monkeypatch.setattr(api, "_enqueue", enqueue)

    result = await api.sync_page(
        source.id,
        page.id,
        session=_Session(source, page),
        task_service=object(),
        user=User(user_id=source.owner_id, email="owner@example.com", name="Owner"),
    )

    assert enqueue.await_args.kwargs["page_id"] == page.id
    assert source.status == "processing"
    assert page.status == "processing"
    assert result == {"id": page.id, "status": "processing", "task_id": "task-1"}


@pytest.mark.asyncio
async def test_sync_rejects_a_source_marked_for_deletion():
    source = WebsiteSource(
        id="source-deleting",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        deleting=True,
    )

    with pytest.raises(api.HTTPException, match="being deleted"):
        await api.sync_source(
            source.id,
            session=_Session(source),
            task_service=object(),
            user=User(user_id=source.owner_id, email="owner@example.com", name="Owner"),
        )


@pytest.mark.asyncio
async def test_source_deletion_marks_durable_state_before_waiting_for_task(monkeypatch):
    source = WebsiteSource(
        id="source-delete",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        status="processing",
        last_task_id="task-delete",
    )
    session = _Session(source)

    async def cancel_task(owner_id, task_id):
        assert owner_id == source.owner_id
        assert task_id == source.last_task_id
        assert source.deleting is True
        assert source.status == "deleting"
        return True

    task_service = type("TaskService", (), {"cancel_task": AsyncMock(side_effect=cancel_task)})()
    delete_chunks = AsyncMock()
    delete_projection = AsyncMock()
    monkeypatch.setattr(api, "delete_source_chunks", delete_chunks)
    monkeypatch.setattr(api, "delete_source_projection", delete_projection)

    result = await api.delete_source(
        source.id,
        session=session,
        task_service=task_service,
        user=User(user_id=source.owner_id, email="owner@example.com", name="Owner"),
    )

    assert result == {"deleted": True, "child_count": 1}
    task_service.cancel_task.assert_awaited_once_with(source.owner_id, "task-delete")
    delete_chunks.assert_awaited_once_with(source.id)
    delete_projection.assert_awaited_once_with(source.id)
    assert session.deleted == [source]
