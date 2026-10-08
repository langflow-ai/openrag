"""Task processor for one managed URL source crawl."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from models.processors import TaskProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

from .crawler import CrawlResult, crawl
from .policy import CrawlSpec
from .projection import (
    delete_page_chunks,
    delete_source_chunks,
    get_page_index_metadata,
    get_page_manifest,
    get_source_manifest,
    list_page_manifests,
    upsert_page_manifest,
    upsert_source_manifest,
)


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
        page_id: str | None = None,
    ):
        super().__init__(document_service=document_service, models_service=models_service)
        self.source_id = source_id
        self.owner_id = owner_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.page_id = page_id

    async def _source_is_active(self) -> dict[str, Any]:
        source = await get_source_manifest(self.source_id)
        if source is None or source.get("deleting"):
            raise ValueError("Website source no longer exists")
        return source

    @staticmethod
    def _new_page(source: dict[str, Any], page_id: str, canonical_url: str) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        return {
            "web_source_id": source["id"],
            "web_page_id": page_id,
            "content_document_id": _document_id(source["id"], canonical_url),
            "canonical_url": canonical_url,
            "source_url": canonical_url,
            "filename": canonical_url,
            "mimetype": "text/html",
            "file_size": 0,
            "chunk_count": 0,
            "status": "unavailable",
            "suppressed_by_user": False,
            "last_seen_at": now,
            "updated_at": now,
        }

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        source = await self._source_is_active()
        target_page = (
            await get_page_manifest(source["id"], self.page_id)
            if self.page_id is not None
            else None
        )
        if self.page_id is not None and target_page is None:
            raise ValueError("Website page no longer exists")

        pages = await list_page_manifests(source["id"])
        pages_by_url = {str(page["canonical_url"]): page for page in pages}
        source_is_established = bool(source.get("last_successful_sync_at")) or bool(pages)
        started_at = datetime.now(UTC)
        source.update(status="processing", last_error=None, updated_at=started_at.isoformat())
        await upsert_source_manifest(source, pages=pages)

        spec_values = dict(source["crawl_settings"])
        if target_page is not None:
            spec_values.update(
                seed_url=target_page["canonical_url"], scope="page", max_pages=1, max_depth=0
            )
        elif source_is_established and source.get("resync_behavior") == "root":
            spec_values.update(scope="page", max_pages=1, max_depth=0)

        try:
            result = await crawl(CrawlSpec(**spec_values))
            if not result.pages and not result.reason and not result.capped:
                result = await crawl(CrawlSpec(**spec_values))
        except Exception as exc:
            result = CrawlResult(
                (), complete=False, capped=False, reason=str(exc) or "Website crawl failed"
            )

        indexed = 0
        successful_pages = 0
        page_errors: list[str] = []
        for outcome in result.pages:
            page = pages_by_url.get(outcome.canonical_url)
            if page is None:
                page = self._new_page(source, str(uuid.uuid4()), outcome.canonical_url)
                pages_by_url[outcome.canonical_url] = page
            page_depth = outcome.depth
            if (
                target_page is not None
                and page.get("web_page_id") == target_page.get("web_page_id")
                and page.get("web_page_depth") is not None
            ):
                # A page-scoped crawl starts at the selected page, so Scrapy
                # reports depth 0. Keep the source-relative depth already
                # recorded for that page instead of replacing it with 0.
                page_depth = int(page["web_page_depth"])
            page.setdefault(
                "content_document_id", _document_id(source["id"], outcome.canonical_url)
            )
            now = datetime.now(UTC).isoformat()
            page.update(
                final_url=outcome.final_url,
                source_url=outcome.final_url,
                web_page_depth=page_depth,
                canonical_url=outcome.canonical_url,
                last_seen_at=now,
                updated_at=now,
            )

            # Task failures are ephemeral, just like ordinary document uploads.
            # Do not overwrite an existing page manifest with a transient failure.
            if outcome.error:
                page_errors.append(outcome.error)
                continue
            if outcome.document is None or outcome.noindex:
                if outcome.noindex:
                    await delete_page_chunks(str(page["content_document_id"]))
                    page["chunk_count"] = 0
                page["status"] = "unavailable"
                await upsert_page_manifest(page)
                continue

            document = outcome.document
            page.update(
                filename=document.title,
                file_size=document.byte_size,
                mimetype="text/html",
            )
            if page.get("suppressed_by_user"):
                page["status"] = "disabled"
                await upsert_page_manifest(page)
                successful_pages += 1
                continue
            if (
                source.get("change_detection") == "normalized_content_hash"
                and page.get("content_hash") == document.content_hash
                and page.get("status") == "active"
                and int(page.get("chunk_count") or 0) > 0
            ):
                await upsert_page_manifest(page)
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
                        file_hash=str(page["content_document_id"]),
                        document_id=str(page["content_document_id"]),
                        replace_existing=True,
                        owner_user_id=self.owner_id,
                        jwt_token=self.jwt_token,
                        owner_name=self.owner_name,
                        owner_email=self.owner_email,
                        file_size=document.byte_size,
                        original_filename=document.title,
                        connector_type="url",
                        source_url=outcome.final_url,
                        web_source_id=source["id"],
                        web_page_id=str(page["web_page_id"]),
                        web_page_depth=page_depth,
                        root_source_url=source["starting_url"],
                        canonical_url=outcome.canonical_url,
                        before_index_write=self._source_is_active,
                    )
                except Exception as exc:
                    page_errors.append(str(exc) or "Website page ingestion failed")
                    continue
                if processed.get("status") == "error":
                    page_errors.append(processed.get("error") or "Failed to ingest website page")
                    continue
                embedding_metadata = await get_page_index_metadata(str(page["content_document_id"]))
                page.update(
                    content_hash=document.content_hash,
                    chunk_count=processed.get("chunk_count", 0),
                    embedding_model=embedding_metadata.get("embedding_model", ""),
                    embedding_provider=embedding_metadata.get("embedding_provider", ""),
                    embedding_space_id=embedding_metadata.get("embedding_space_id", ""),
                    embedding_dimensions=embedding_metadata.get("embedding_dimensions"),
                    status="active",
                    last_ingested_at=datetime.now(UTC).isoformat(),
                    last_error=None,
                )
                await upsert_page_manifest(page)
                indexed, successful_pages = indexed + 1, successful_pages + 1
            finally:
                try:
                    os.unlink(handle.name)
                except FileNotFoundError:
                    pass

        if target_page is None and source.get("resync_behavior") == "full" and result.complete:
            for page in pages_by_url.values():
                if (
                    page.get("suppressed_by_user")
                    or page.get("last_seen_at", "") >= started_at.isoformat()
                ):
                    continue
                page["status"] = "unavailable"
                page["updated_at"] = datetime.now(UTC).isoformat()
                if source.get("removed_page_behavior") == "delete":
                    await delete_page_chunks(str(page["content_document_id"]))
                    page["chunk_count"] = 0
                await upsert_page_manifest(page)

        failure_reason = (
            result.reason
            or next(iter(page_errors), None)
            or "No indexable website pages were found."
        )
        try:
            source = await self._source_is_active()
        except ValueError:
            failure_reason = "Website source was deleted"
            succeeded = False
        else:
            succeeded = successful_pages > 0
            if not succeeded and target_page is not None:
                final_page = pages_by_url.get(str(target_page["canonical_url"]), target_page)
                if final_page.get("status") == "processing":
                    final_page.update(
                        status="failed",
                        last_error=failure_reason,
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    await upsert_page_manifest(final_page)
            source["status"] = "active" if succeeded or source_is_established else "failed"
            source["last_error"] = (
                None if source_is_established else (None if succeeded else failure_reason)
            )
            if succeeded:
                source["last_successful_sync_at"] = datetime.now(UTC).isoformat()
            source["updated_at"] = datetime.now(UTC).isoformat()

            if not succeeded and not source_is_established:
                await delete_source_chunks(source["id"])
            else:
                await upsert_source_manifest(source, pages=await list_page_manifests(source["id"]))

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
