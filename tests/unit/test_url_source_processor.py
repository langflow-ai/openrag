"""Task-state coverage for the managed URL source processor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

import db.engine as engine
from connectors.url.crawler import CrawledPage, CrawlResult
from connectors.url.document import WebDocument
from connectors.url.processor import WebsiteSourceProcessor
from db.models.website_source import WebsiteCrawlRun, WebsitePage, WebsiteSource
from models.tasks import FileTask, TaskStatus, UploadTask


class _ScalarResult:
    def __init__(self, scalar=None):
        self.scalar = scalar

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return []


class _Session:
    def __init__(self, source: WebsiteSource, existing_page=None):
        self.source = source
        self.existing_page = existing_page
        self.commits = 0
        self.deleted: list[object] = []
        self.added: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, _, source_id: str):
        assert source_id == self.source.id
        return self.source

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.commits += 1

    async def execute(self, _):
        return _ScalarResult(self.existing_page)


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
        status="failed",
        last_successful_sync_at=datetime.now(UTC),
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


@pytest.mark.asyncio
async def test_crawl_exception_marks_the_task_failed_and_keeps_an_established_source(monkeypatch):
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-3",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        status="failed",
        last_successful_sync_at=datetime.now(UTC),
    )
    session = _Session(source)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        processor_module, "crawl", AsyncMock(side_effect=RuntimeError("network down"))
    )
    upsert_source_projection = AsyncMock()
    monkeypatch.setattr(processor_module, "upsert_source_projection", upsert_source_projection)
    monkeypatch.setattr(processor_module, "delete_source_projection", AsyncMock())

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    upload_task = UploadTask(task_id="task-3", total_files=1)
    file_task = FileTask(file_path="website:source-3")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    run = next(item for item in session.added if item.__class__.__name__ == "WebsiteCrawlRun")
    assert source.status == "failed"
    assert source.last_error == "network down"
    assert run.error == "network down"
    assert session.deleted == []
    assert upsert_source_projection.await_count == 2
    assert file_task.status is TaskStatus.FAILED
    assert file_task.error == "network down"


@pytest.mark.asyncio
async def test_projection_failure_marks_an_established_source_failed(monkeypatch):
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-projection-failure",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        last_successful_sync_at=datetime.now(UTC),
    )
    session = _Session(source)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(processor_module, "crawl", AsyncMock())
    monkeypatch.setattr(
        processor_module,
        "upsert_source_projection",
        AsyncMock(side_effect=[RuntimeError("OpenSearch unavailable"), None]),
    )
    monkeypatch.setattr(processor_module, "delete_source_projection", AsyncMock())

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    upload_task = UploadTask(task_id="task-projection-failure", total_files=1)
    file_task = FileTask(file_path=f"website:{source.id}")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    run = next(item for item in session.added if isinstance(item, WebsiteCrawlRun))
    assert source.status == "failed"
    assert source.last_error == "OpenSearch unavailable"
    assert run.error == "OpenSearch unavailable"
    assert session.deleted == []
    assert file_task.status is TaskStatus.FAILED
    assert file_task.error == "OpenSearch unavailable"


@pytest.mark.asyncio
async def test_page_ingestion_exception_marks_the_page_and_source_failed(monkeypatch):
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-4",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        last_successful_sync_at=datetime.now(UTC),
    )
    session = _Session(source)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult(
                (
                    CrawledPage(
                        canonical_url="https://docs.example.com/guide",
                        final_url="https://docs.example.com/guide",
                        depth=1,
                        document=WebDocument(
                            title="Guide",
                            markdown="# Guide\n\nContent\n",
                            content_hash="content-hash",
                            byte_size=18,
                        ),
                    ),
                ),
                complete=True,
                capped=False,
            )
        ),
    )
    monkeypatch.setattr(processor_module, "upsert_source_projection", AsyncMock())
    monkeypatch.setattr(processor_module, "delete_source_projection", AsyncMock())

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    processor.process_document_standard = AsyncMock(side_effect=RuntimeError("ingestion down"))
    upload_task = UploadTask(task_id="task-4", total_files=1)
    file_task = FileTask(file_path="website:source-4")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    page = next(item for item in session.added if isinstance(item, WebsitePage))
    assert page.status == "failed"
    assert page.last_error == "ingestion down"
    assert source.status == "failed"
    assert source.last_error == "ingestion down"
    assert file_task.status is TaskStatus.FAILED


@pytest.mark.asyncio
async def test_always_reingest_processes_an_unchanged_page(monkeypatch):
    from connectors.url import processor as processor_module

    source = WebsiteSource(
        id="source-5",
        owner_id="owner-1",
        name="Documentation",
        starting_url="https://docs.example.com/",
        crawl_settings={"seed_url": "https://docs.example.com/"},
        change_detection="always_reingest",
        last_successful_sync_at=datetime.now(UTC),
    )
    existing_page = WebsitePage(
        id="page-5",
        web_source_id=source.id,
        canonical_url="https://docs.example.com/guide",
        title="Guide",
        document_id="document-5",
        content_hash="same-content",
        chunk_count=1,
        status="active",
    )
    session = _Session(source, existing_page)
    monkeypatch.setattr(processor_module, "SessionLocal", object())
    monkeypatch.setattr(engine, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult(
                (
                    CrawledPage(
                        canonical_url=existing_page.canonical_url,
                        final_url=existing_page.canonical_url,
                        depth=1,
                        document=WebDocument(
                            title="Guide",
                            markdown="# Guide\n\nContent\n",
                            content_hash="same-content",
                            byte_size=18,
                        ),
                    ),
                ),
                complete=True,
                capped=False,
            )
        ),
    )
    monkeypatch.setattr(processor_module, "upsert_source_projection", AsyncMock())
    monkeypatch.setattr(processor_module, "delete_source_projection", AsyncMock())

    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=source.owner_id,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        document_service=None,
        models_service=None,
    )
    processor.process_document_standard = AsyncMock(
        return_value={"status": "indexed", "chunk_count": 1}
    )
    upload_task = UploadTask(task_id="task-5", total_files=1)
    file_task = FileTask(file_path="website:source-5")

    await processor.process_item(upload_task, file_task.file_path, file_task)

    processor.process_document_standard.assert_awaited_once()
    assert existing_page.status == "active"
    assert file_task.status is TaskStatus.COMPLETED
