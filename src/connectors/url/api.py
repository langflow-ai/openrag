"""HTTP API for managed URL sources."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import is_url_connector_enabled
from db.models.website_source import WebsitePage, WebsiteSource
from dependencies import get_current_user, get_db_session, get_task_service, require_permission
from session_manager import User

from .policy import CrawlPolicyError, CrawlSpec
from .processor import WebsiteSourceProcessor
from .projection import (
    delete_page_chunks,
    delete_source_chunks,
    delete_source_projection,
)


def require_url_connector_enabled() -> None:
    """Reject URL source calls while the managed connector is disabled."""
    if not is_url_connector_enabled():
        raise HTTPException(status_code=404, detail="Website connector is not enabled")


class CreateSourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    starting_url: str
    scope: Literal["page", "path", "site"] = "path"
    allow_subdomains: bool = False
    additional_hosts: list[str] = Field(default_factory=list)
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=250, ge=1, le=10_000)
    max_depth: int = Field(default=4, ge=0, le=20)
    max_downloaded_mb: int = Field(default=128, ge=1, le=2048)
    max_crawl_minutes: int = Field(default=15, ge=1, le=60)
    resync_behavior: Literal["full", "root"] = "full"
    removed_page_behavior: Literal["retain", "delete"] = "retain"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Connection name is required")
        return value

    def spec(self) -> CrawlSpec:
        values = self.model_dump(exclude={"name", "resync_behavior", "removed_page_behavior"})
        if values["scope"] == "page":
            values["max_pages"], values["max_depth"] = 1, 0
        return CrawlSpec(seed_url=values.pop("starting_url"), **values)


def _view(source: WebsiteSource, count: int | None = None) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "starting_url": source.starting_url,
        "status": source.status,
        "last_error": source.last_error,
        "last_task_id": source.last_task_id,
        "last_successful_sync_at": source.last_successful_sync_at,
        "web_child_count": count,
        "connector_type": "url",
    }


async def _owned(session: AsyncSession, source_id: str, user: User) -> WebsiteSource:
    source = await session.get(WebsiteSource, source_id)
    if source is None or source.owner_id != user.user_id:
        raise HTTPException(404, "Website source not found")
    return source


async def _enqueue(source: WebsiteSource, user: User, task_service) -> str:
    processor = WebsiteSourceProcessor(
        source_id=source.id,
        owner_id=user.user_id,
        jwt_token=user.jwt_token,
        owner_name=getattr(user, "name", None),
        owner_email=getattr(user, "email", None),
        document_service=task_service.document_service,
        models_service=task_service.models_service,
    )
    return await task_service.create_custom_task(
        user.user_id, [source.id], processor, original_filenames={source.id: source.name}
    )


async def create_source(
    body: CreateSourceBody,
    session: AsyncSession = Depends(get_db_session),
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    try:
        spec = body.spec()
    except CrawlPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    source = WebsiteSource(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        name=body.name,
        starting_url=spec.seed_url,
        crawl_settings=spec.as_dict(),
        resync_behavior=body.resync_behavior,
        removed_page_behavior=body.removed_page_behavior,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    try:
        source.last_task_id = await _enqueue(source, user, task_service)
    except Exception:
        # Match ordinary uploads: if no task can be created, leave no
        # unattached source record behind.
        await session.delete(source)
        await session.commit()
        raise
    await session.commit()
    return _view(source, 0)


async def list_sources(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
):
    rows = (
        await session.execute(
            select(WebsiteSource, func.count(WebsitePage.id))
            .outerjoin(WebsitePage)
            .where(WebsiteSource.owner_id == user.user_id)
            .group_by(WebsiteSource.id)
        )
    ).all()
    return {"sources": [_view(source, count) for source, count in rows]}


async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    source = await _owned(session, source_id, user)
    count = (
        await session.execute(
            select(func.count())
            .select_from(WebsitePage)
            .where(WebsitePage.web_source_id == source.id)
        )
    ).scalar_one()
    return _view(source, count)


async def sync_source(
    source_id: str,
    session: AsyncSession = Depends(get_db_session),
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    source = await _owned(session, source_id, user)
    if source.status == "processing":
        raise HTTPException(409, "A crawl is already running")
    source.status = "processing"
    source.last_task_id = await _enqueue(source, user, task_service)
    await session.commit()
    return _view(source)


async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permission("connectors:delete:own")),
):
    source = await _owned(session, source_id, user)
    count = (
        await session.execute(
            select(func.count())
            .select_from(WebsitePage)
            .where(WebsitePage.web_source_id == source.id)
        )
    ).scalar_one()
    await delete_source_chunks(source.id)
    await delete_source_projection(source.id)
    await session.delete(source)
    await session.commit()
    return {"deleted": True, "child_count": count}


async def delete_page(
    source_id: str,
    page_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permission("knowledge:delete:own")),
):
    await _owned(session, source_id, user)
    page = await session.get(WebsitePage, page_id)
    if page is None or page.web_source_id != source_id:
        raise HTTPException(404, "Website page not found")
    await delete_page_chunks(page.document_id)
    page.suppressed_by_user, page.status, page.chunk_count, page.updated_at = (
        True,
        "disabled",
        0,
        datetime.now(UTC),
    )
    await session.commit()
    return {"id": page.id, "status": page.status}


async def sync_page(
    source_id: str,
    page_id: str,
    session: AsyncSession = Depends(get_db_session),
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    source = await _owned(session, source_id, user)
    if source.status == "processing":
        raise HTTPException(409, "A crawl is already running")
    page = await session.get(WebsitePage, page_id)
    if page is None or page.web_source_id != source_id:
        raise HTTPException(404, "Website page not found")
    page.suppressed_by_user, page.status, page.updated_at = False, "processing", datetime.now(UTC)
    source.status = "processing"
    source.last_task_id = await _enqueue(source, user, task_service)
    await session.commit()
    return {"id": page.id, "status": page.status, "task_id": source.last_task_id}
