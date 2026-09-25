"""Task-state coverage for the managed URL source processor."""

from unittest.mock import AsyncMock

import pytest

import db.engine as engine
from connectors.url.crawler import CrawlResult
from connectors.url.processor import WebsiteSourceProcessor
from db.models.website_source import WebsiteSource
from models.tasks import FileTask, TaskStatus, UploadTask


class _ScalarResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _Session:
    def __init__(self, source: WebsiteSource):
        self.source = source
        self.commits = 0
        self.deleted: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, _, source_id: str):
        assert source_id == self.source.id
        return self.source

    def add(self, _):
        return None

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.commits += 1

    async def execute(self, _):
        return _ScalarResult()


@pytest.mark.asyncio
async def test_empty_url_crawl_fails_its_file_task_with_a_visible_reason(monkeypatch):
    """A source failure must not be reported as a successful ingestion task."""
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-1",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
    )
    session = _Session(source)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(return_value=CrawlResult((), complete=True, capped=False)),
    )
    monkeypatch.setattr(processor_module, "upsert_source_projection", AsyncMock())
    delete_source_projection = AsyncMock()
    monkeypatch.setattr(processor_module, "delete_source_projection", delete_source_projection)

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    upload_task = UploadTask(task_id="task-1", total_files=1)
    file_task = FileTask(file_path="website:source-1")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    assert source.status == "failed"
    assert source.last_error == "No indexable website pages were found."
    assert session.deleted == [source]
    delete_source_projection.assert_awaited_once_with(source.id)
    assert file_task.status is TaskStatus.FAILED
    assert file_task.error == source.last_error
    assert upload_task.successful_files == 0
    assert upload_task.failed_files == 1


@pytest.mark.asyncio
async def test_failed_resync_keeps_an_established_website_source(monkeypatch):
    """A transient re-sync error must not remove previously indexed knowledge."""
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-2",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        status="active",
    )
    session = _Session(source)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(return_value=CrawlResult((), complete=True, capped=False)),
    )
    upsert_source_projection = AsyncMock()
    monkeypatch.setattr(processor_module, "upsert_source_projection", upsert_source_projection)
    delete_source_projection = AsyncMock()
    monkeypatch.setattr(processor_module, "delete_source_projection", delete_source_projection)

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    upload_task = UploadTask(task_id="task-2", total_files=1)
    file_task = FileTask(file_path="website:source-2")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    assert source.status == "failed"
    assert session.deleted == []
    assert upsert_source_projection.await_count == 2
    delete_source_projection.assert_not_awaited()
    assert file_task.status is TaskStatus.FAILED
