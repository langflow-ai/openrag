"""OpenSearch-manifest coverage for the managed URL source processor."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from connectors.url import processor as processor_module
from connectors.url.crawler import CrawledPage, CrawlResult
from connectors.url.document import WebDocument
from connectors.url.processor import WebsiteSourceProcessor
from models.tasks import FileTask, TaskStatus, UploadTask


def _source(**overrides) -> dict:
    source = {
        "id": "source-1",
        "owner_id": "owner-1",
        "name": "Documentation",
        "starting_url": "https://docs.example.com/",
        "crawl_settings": {"seed_url": "https://docs.example.com/"},
        "status": "processing",
        "resync_behavior": "full",
        "removed_page_behavior": "retain",
        "change_detection": "normalized_content_hash",
        "deleting": False,
    }
    source.update(overrides)
    return source


def _processor(source: dict, *, page_id: str | None = None) -> WebsiteSourceProcessor:
    return WebsiteSourceProcessor(
        source_id=source["id"],
        owner_id=source["owner_id"],
        jwt_token=None,
        owner_name="Owner",
        owner_email="owner@example.com",
        document_service=None,
        models_service=None,
        page_id=page_id,
    )


def _page(source: dict, url: str, *, page_id: str = "page-1", **overrides) -> dict:
    return {
        "web_source_id": source["id"],
        "web_page_id": page_id,
        "document_id": f"web-page:{source['id']}:{page_id}",
        "content_document_id": f"document-{page_id}",
        "canonical_url": url,
        "source_url": url,
        "filename": "Existing page",
        "mimetype": "text/html",
        "file_size": 10,
        "chunk_count": 2,
        "status": "active",
        "last_seen_at": datetime.now(UTC).isoformat(),
        **overrides,
    }


@pytest.mark.asyncio
async def test_crawl_writes_page_manifest_and_parent_summary(monkeypatch):
    source = _source()
    manifests: list[dict] = []
    projection = AsyncMock()
    document = WebDocument("Guide", "# Guide\n\nContent", "hash-1", 512)

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(
        processor_module, "upsert_page_manifest", AsyncMock(side_effect=manifests.append)
    )
    monkeypatch.setattr(processor_module, "upsert_source_manifest", projection)
    monkeypatch.setattr(
        processor_module,
        "get_page_index_metadata",
        AsyncMock(
            return_value={
                "embedding_model": "text-embedding-3-small",
                "embedding_provider": "azure",
                "embedding_dimensions": 1536,
            }
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult(
                (
                    CrawledPage(
                        "https://docs.example.com/guide",
                        "https://docs.example.com/guide",
                        1,
                        document,
                    ),
                ),
                complete=True,
                capped=False,
            )
        ),
    )
    monkeypatch.setattr(
        WebsiteSourceProcessor,
        "process_document_standard",
        AsyncMock(return_value={"status": "indexed", "chunk_count": 3}),
    )

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    await _processor(source).process_item(task, file_task.file_path, file_task)

    page = manifests[0]
    assert page["web_source_id"] == source["id"]
    assert page["chunk_count"] == 3
    assert page["embedding_dimensions"] == 1536
    assert projection.await_args_list[-1].kwargs["pages"] == manifests
    assert file_task.status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_initial_crawl_keeps_saved_scope_when_future_resync_is_root_only(monkeypatch):
    source = _source(resync_behavior="root")
    manifests: list[dict] = []
    document = WebDocument("Guide", "# Guide\n\nContent", "hash-1", 512)
    crawl = AsyncMock(
        return_value=CrawlResult(
            (
                CrawledPage(
                    "https://docs.example.com/guide",
                    "https://docs.example.com/guide",
                    1,
                    document,
                ),
            ),
            complete=True,
            capped=False,
        )
    )

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(
        processor_module, "upsert_page_manifest", AsyncMock(side_effect=manifests.append)
    )
    monkeypatch.setattr(processor_module, "upsert_source_manifest", AsyncMock())
    monkeypatch.setattr(processor_module, "crawl", crawl)
    monkeypatch.setattr(
        WebsiteSourceProcessor,
        "process_document_standard",
        AsyncMock(return_value={"status": "indexed", "chunk_count": 1}),
    )
    monkeypatch.setattr(processor_module, "get_page_index_metadata", AsyncMock(return_value={}))

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    await _processor(source).process_item(task, file_task.file_path, file_task)

    spec = crawl.await_args.args[0]
    assert spec.scope == "path"
    assert spec.max_pages == 250


@pytest.mark.asyncio
async def test_failed_resync_keeps_existing_page_manifests_and_source_active(monkeypatch):
    source = _source(last_successful_sync_at=datetime.now(UTC).isoformat())
    manifests = [_page(source, "https://docs.example.com/guide")]
    upsert_page = AsyncMock()

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(processor_module, "upsert_page_manifest", upsert_page)
    monkeypatch.setattr(processor_module, "upsert_source_manifest", AsyncMock())
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult((), complete=False, capped=False, reason="network down")
        ),
    )

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    await _processor(source).process_item(task, file_task.file_path, file_task)

    assert source["status"] == "active"
    assert manifests[0]["status"] == "active"
    upsert_page.assert_not_awaited()
    assert file_task.status is TaskStatus.FAILED
    assert file_task.error == "network down"


@pytest.mark.asyncio
async def test_failed_page_resync_replaces_processing_status_with_error(monkeypatch):
    source = _source(last_successful_sync_at=datetime.now(UTC).isoformat())
    page = _page(source, "https://docs.example.com/guide", status="processing")
    manifests = [page]
    persist_page = AsyncMock()

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(processor_module, "get_page_manifest", AsyncMock(return_value=page))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(processor_module, "upsert_page_manifest", persist_page)
    monkeypatch.setattr(processor_module, "upsert_source_manifest", AsyncMock())
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult((), complete=False, capped=False, reason="network down")
        ),
    )

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    await _processor(source, page_id=page["web_page_id"]).process_item(
        task, file_task.file_path, file_task
    )

    assert page["status"] == "failed"
    assert page["last_error"] == "network down"
    persist_page.assert_awaited_once_with(page)


@pytest.mark.asyncio
async def test_page_resync_preserves_existing_source_relative_depth(monkeypatch):
    source = _source(last_successful_sync_at=datetime.now(UTC).isoformat())
    page = _page(source, "https://docs.example.com/guides/deep", web_page_depth=3)
    manifests = [page]
    document = WebDocument("Deep guide", "# Guide\n\nContent", "hash-2", 512)

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(processor_module, "get_page_manifest", AsyncMock(return_value=page))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(processor_module, "upsert_page_manifest", AsyncMock())
    monkeypatch.setattr(processor_module, "upsert_source_manifest", AsyncMock())
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult(
                (CrawledPage(page["canonical_url"], page["canonical_url"], 0, document),),
                complete=True,
                capped=False,
            )
        ),
    )
    monkeypatch.setattr(
        WebsiteSourceProcessor,
        "process_document_standard",
        AsyncMock(return_value={"status": "indexed", "chunk_count": 3}),
    )
    monkeypatch.setattr(processor_module, "get_page_index_metadata", AsyncMock(return_value={}))

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    processor = _processor(source, page_id=page["web_page_id"])
    await processor.process_item(task, file_task.file_path, file_task)

    assert page["web_page_depth"] == 3
    assert processor.process_document_standard.await_args.kwargs["web_page_depth"] == 3


@pytest.mark.asyncio
async def test_complete_full_crawl_marks_missing_manifest_unavailable(monkeypatch):
    source = _source(
        last_successful_sync_at=datetime.now(UTC).isoformat(), removed_page_behavior="delete"
    )
    stale = _page(
        source,
        "https://docs.example.com/removed",
        last_seen_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    manifests = [stale]
    delete_chunks = AsyncMock()

    monkeypatch.setattr(processor_module, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(
        processor_module, "list_page_manifests", AsyncMock(side_effect=lambda *_: manifests)
    )
    monkeypatch.setattr(processor_module, "upsert_page_manifest", AsyncMock())
    monkeypatch.setattr(processor_module, "upsert_source_manifest", AsyncMock())
    monkeypatch.setattr(processor_module, "delete_page_chunks", delete_chunks)
    monkeypatch.setattr(
        processor_module,
        "crawl",
        AsyncMock(
            return_value=CrawlResult((), complete=True, capped=False, reason="crawl completed")
        ),
    )

    task, file_task = UploadTask(task_id="task-1", total_files=1), FileTask(file_path="source-1")
    await _processor(source).process_item(task, file_task.file_path, file_task)

    assert stale["status"] == "unavailable"
    assert stale["chunk_count"] == 0
    delete_chunks.assert_awaited_once_with(stale["content_document_id"])
    assert file_task.status is TaskStatus.FAILED
