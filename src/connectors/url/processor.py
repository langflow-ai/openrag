"""Task processor for one URL source crawl.

It intentionally uses TaskProcessor.process_document_standard so web pages
follow the same native conversion, embeddings and index-writer path as uploads.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlmodel import col

from db.engine import SessionLocal, init_engine
from db.models.website_source import WebsiteCrawlRun, WebsitePage, WebsiteSource
from models.processors import TaskProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

from .crawler import CrawlResult, crawl
from .policy import CrawlSpec
from .projection import delete_page_chunks, delete_source_projection, upsert_source_projection


def _document_id(source_id: str, canonical_url: str) -> str:
    return hashlib.sha256(f"{source_id}\0{canonical_url}".encode()).hexdigest()


class WebsiteSourceProcessor(TaskProcessor):
    def __init__(
        self,
        *,
        source_id: str,
        owner_id: str,
        jwt_token: str | None,
        owner_name: str | None,
        owner_email: str | None,
        document_service,
        models_service,
    ):
        super().__init__(document_service=document_service, models_service=models_service)
        self.source_id = source_id
        self.owner_id = owner_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        if SessionLocal is None:
            init_engine()
        from db.engine import SessionLocal as sessions

        assert sessions is not None
        async with sessions() as session:
            source = await session.get(WebsiteSource, self.source_id)
            if source is None:
                raise ValueError("Website source no longer exists")
            source_is_established = source.last_successful_sync_at is not None
            if not source_is_established:
                source_is_established = (
                    await session.execute(
                        select(col(WebsitePage.id))
                        .where(col(WebsitePage.web_source_id) == source.id)
                        .limit(1)
                    )
                ).scalar_one_or_none() is not None
            started_at = datetime.now(UTC)
            source.status = "processing"
            run = WebsiteCrawlRun(
                id=str(uuid.uuid4()),
                web_source_id=source.id,
                task_id=upload_task.task_id,
                settings_snapshot=source.crawl_settings,
            )
            session.add(run)
            await session.commit()
            if source_is_established:
                await upsert_source_projection(source)
            spec_values = dict(source.crawl_settings)
            if source.resync_behavior == "root":
                spec_values.update(scope="page", max_pages=1, max_depth=0)
            try:
                result = await crawl(CrawlSpec(**spec_values))
            except Exception as exc:
                result = CrawlResult(
                    (),
                    complete=False,
                    capped=False,
                    reason=str(exc) or "Website crawl failed",
                )
            indexed = 0
            successful_pages = 0
            page_errors: list[str] = []
            for outcome in result.pages:
                existing = (
                    await session.execute(
                        select(WebsitePage).where(
                            col(WebsitePage.web_source_id) == source.id,
                            col(WebsitePage.canonical_url) == outcome.canonical_url,
                        )
                    )
                ).scalar_one_or_none()
                page = existing or WebsitePage(
                    id=str(uuid.uuid4()),
                    web_source_id=source.id,
                    canonical_url=outcome.canonical_url,
                    final_url=outcome.final_url,
                    title=outcome.canonical_url,
                    document_id=_document_id(source.id, outcome.canonical_url),
                )
                if existing is None:
                    session.add(page)
                page.final_url, page.depth, page.last_seen_at, page.updated_at = (
                    outcome.final_url,
                    outcome.depth,
                    datetime.now(UTC),
                    datetime.now(UTC),
                )
                if outcome.error:
                    page.status, page.last_error = "failed", outcome.error
                    page_errors.append(outcome.error)
                    continue
                if outcome.document is None or outcome.noindex:
                    page.status = "unavailable"
                    continue
                document = outcome.document
                page.title, page.byte_size, page.content_type = (
                    document.title,
                    document.byte_size,
                    "text/html",
                )
                if page.suppressed_by_user:
                    page.status = "disabled"
                    continue
                if (
                    source.change_detection == "normalized_content_hash"
                    and
                    page.content_hash == document.content_hash
                    and page.status == "active"
                    and page.chunk_count > 0
                ):
                    page.status = "active"
                    page.last_error = None
                    successful_pages += 1
                    continue
                handle = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                )
                try:
                    handle.write(document.markdown)
                    handle.close()
                    try:
                        processed = await self.process_document_standard(
                            file_path=handle.name,
                            file_hash=page.document_id,
                            document_id=page.document_id,
                            replace_existing=True,
                            owner_user_id=self.owner_id,
                            jwt_token=self.jwt_token,
                            owner_name=self.owner_name,
                            owner_email=self.owner_email,
                            file_size=document.byte_size,
                            original_filename=document.title,
                            connector_type="url",
                            source_url=outcome.final_url,
                            web_source_id=source.id,
                            web_page_id=page.id,
                            web_page_depth=outcome.depth,
                            root_source_url=source.starting_url,
                            canonical_url=outcome.canonical_url,
                        )
                    except Exception as exc:
                        page.status, page.last_error = (
                            "failed",
                            str(exc) or "Website page ingestion failed",
                        )
                        page_errors.append(page.last_error)
                        continue
                    if processed.get("status") == "error":
                        page.status, page.last_error = (
                            "failed",
                            (processed.get("error") or "Failed to ingest website page"),
                        )
                        page_errors.append(page.last_error)
                    else:
                        page.content_hash, page.chunk_count, page.status = (
                            document.content_hash,
                            processed.get("chunk_count", 0),
                            "active",
                        )
                        page.last_error = None
                        page.last_ingested_at, indexed = datetime.now(UTC), indexed + 1
                        successful_pages += 1
                finally:
                    try:
                        os.unlink(handle.name)
                    except FileNotFoundError:
                        pass
            if source.resync_behavior == "full" and result.complete:
                missing = (
                    (
                        await session.execute(
                            select(WebsitePage).where(
                                col(WebsitePage.web_source_id) == source.id,
                                col(WebsitePage.last_seen_at) < started_at,
                                col(WebsitePage.suppressed_by_user).is_(False),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for page in missing:
                    page.status = "unavailable"
                    if source.removed_page_behavior == "delete":
                        await delete_page_chunks(page.document_id)
                        page.chunk_count = 0
            failure_reason = (
                result.reason
                or next(iter(page_errors), None)
                or "No indexable website pages were found."
            )
            succeeded = successful_pages > 0
            source.status = "active" if succeeded else "failed"
            source.last_error = result.reason if succeeded else failure_reason
            if result.complete and succeeded:
                source.last_successful_sync_at = datetime.now(UTC)
            source.updated_at = datetime.now(UTC)
            run.completed, run.capped, run.error, run.finished_at = (
                result.complete and succeeded,
                result.capped,
                source.last_error,
                datetime.now(UTC),
            )
            await session.commit()
            discard_failed_new_source = not succeeded and not source_is_established
            if discard_failed_new_source:
                # Failed regular uploads never become Knowledge records. Do the
                # same for a URL source that has never successfully indexed a
                # page, so a task-expired failure cannot become an orphaned row.
                await delete_source_projection(source.id)
                await session.execute(
                    delete(WebsitePage).where(col(WebsitePage.web_source_id) == source.id)
                )
                await session.execute(
                    delete(WebsiteCrawlRun).where(col(WebsiteCrawlRun.web_source_id) == source.id)
                )
                await session.delete(source)
                await session.commit()
            else:
                child_count = (
                    (
                        await session.execute(
                            select(WebsitePage).where(col(WebsitePage.web_source_id) == source.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                await upsert_source_projection(source, child_count=len(child_count))
        if not succeeded:
            file_task.status, file_task.error, file_task.result, file_task.updated_at = (
                TaskStatus.FAILED,
                failure_reason,
                {"indexed": 0, "pages": 0},
                time.time(),
            )
            upload_task.failed_files += 1
            return
        file_task.status, file_task.result, file_task.updated_at = (
            TaskStatus.COMPLETED,
            {"indexed": indexed, "pages": successful_pages},
            time.time(),
        )
        upload_task.successful_files += 1
