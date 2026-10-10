"""HTTP API for managed URL sources backed entirely by OpenSearch manifests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from config.settings import is_url_connector_enabled
from dependencies import get_current_user, get_task_service, require_permission
from session_manager import User

from .policy import CrawlPolicyError, CrawlSpec
from .processor import WebsiteSourceProcessor
from .projection import (
    delete_page_chunks,
    delete_source_chunks,
    get_page_manifest,
    get_source_manifest,
    list_page_manifests,
    list_source_manifests,
    upsert_page_manifest,
    upsert_source_manifest,
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
    change_detection: Literal["normalized_content_hash", "always_reingest"] = (
        "normalized_content_hash"
    )
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
        values = self.model_dump(
            exclude={
                "name",
                "change_detection",
                "resync_behavior",
                "removed_page_behavior",
            }
        )
        if values["scope"] == "page":
            values["max_pages"], values["max_depth"] = 1, 0
        return CrawlSpec(seed_url=values.pop("starting_url"), **values)


def _view(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source["id"],
        "name": source["name"],
        "starting_url": source["starting_url"],
        "change_detection": source.get("change_detection", "normalized_content_hash"),
        "status": source.get("status", "active"),
        "deleting": bool(source.get("deleting", False)),
        "last_error": source.get("last_error"),
        "last_task_id": source.get("last_task_id"),
        "last_successful_sync_at": source.get("last_successful_sync_at"),
        "web_child_count": source.get("web_child_count", 0),
        "connector_type": "url",
    }


async def _owned(source_id: str, user: User) -> dict[str, Any]:
    source = await get_source_manifest(source_id)
    if source is None or source.get("owner_id") != user.user_id:
        raise HTTPException(404, "Website source not found")
    return source


async def _enqueue(
    source: dict[str, Any], user: User, task_service, *, page_id: str | None = None
) -> str:
    processor = WebsiteSourceProcessor(
        source_id=source["id"],
        owner_id=user.user_id,
        jwt_token=user.jwt_token,
        owner_name=getattr(user, "name", None),
        owner_email=getattr(user, "email", None),
        document_service=task_service.document_service,
        models_service=task_service.models_service,
        page_id=page_id,
    )
    return await task_service.create_custom_task(
        user.user_id,
        [source["id"]],
        processor,
        original_filenames={source["id"]: source["name"]},
    )


async def create_source(
    body: CreateSourceBody,
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    try:
        spec = body.spec()
    except CrawlPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc

    normalized_name = body.name.casefold()
    existing_sources = await list_source_manifests(user.user_id)
    if any(
        str(source.get("name", "")).strip().casefold() == normalized_name
        for source in existing_sources
    ):
        raise HTTPException(409, "A website connection with this name already exists")

    now = datetime.now(UTC).isoformat()
    source: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "owner_id": user.user_id,
        "owner_name": getattr(user, "name", "") or "",
        "owner_email": getattr(user, "email", "") or "",
        "name": body.name,
        "starting_url": spec.seed_url,
        "crawl_settings": spec.as_dict(),
        "change_detection": body.change_detection,
        "resync_behavior": body.resync_behavior,
        "removed_page_behavior": body.removed_page_behavior,
        "deleting": False,
        "status": "processing",
        "last_error": None,
        "last_task_id": None,
        "last_successful_sync_at": None,
        "allowed_users": [],
        "allowed_groups": [],
        "allowed_principal_labels": [],
        "created_at": now,
        "updated_at": now,
    }
    await upsert_source_manifest(source, pages=[])
    try:
        source["last_task_id"] = await _enqueue(source, user, task_service)
    except Exception:
        await delete_source_chunks(source["id"])
        raise
    await upsert_source_manifest(source, pages=[])
    return _view(source)


async def list_sources(user: User = Depends(get_current_user)):
    return {"sources": [_view(source) for source in await list_source_manifests(user.user_id)]}


async def get_source(source_id: str, user: User = Depends(get_current_user)):
    return _view(await _owned(source_id, user))


async def sync_source(
    source_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    source = await _owned(source_id, user)
    if source.get("deleting"):
        raise HTTPException(409, "Website source is being deleted")
    if source.get("status") == "processing":
        raise HTTPException(409, "A crawl is already running")

    source["status"], source["last_error"], source["updated_at"] = (
        "processing",
        None,
        datetime.now(UTC).isoformat(),
    )
    await upsert_source_manifest(source)
    try:
        source["last_task_id"] = await _enqueue(source, user, task_service)
    except Exception:
        source["status"], source["updated_at"] = "active", datetime.now(UTC).isoformat()
        await upsert_source_manifest(source)
        raise
    await upsert_source_manifest(source)
    return _view(source)


async def delete_source(
    source_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:delete:own")),
):
    source = await _owned(source_id, user)
    source["deleting"], source["status"], source["updated_at"] = (
        True,
        "deleting",
        datetime.now(UTC).isoformat(),
    )
    await upsert_source_manifest(source)
    if task_id := source.get("last_task_id"):
        await task_service.cancel_task(source["owner_id"], task_id)
    count = len(await list_page_manifests(source_id))
    await delete_source_chunks(source_id)
    return {"deleted": True, "child_count": count}


async def delete_page(
    source_id: str,
    page_id: str,
    user: User = Depends(require_permission("knowledge:delete:own")),
):
    source = await _owned(source_id, user)
    page = await get_page_manifest(source_id, page_id)
    if page is None:
        raise HTTPException(404, "Website page not found")
    await delete_page_chunks(str(page.get("content_document_id") or page["document_id"]))
    page.update(
        suppressed_by_user=True,
        status="disabled",
        chunk_count=0,
        updated_at=datetime.now(UTC).isoformat(),
    )
    await upsert_page_manifest(page)
    await upsert_source_manifest(source, pages=await list_page_manifests(source_id))
    return {"id": page_id, "status": "disabled"}


async def sync_page(
    source_id: str,
    page_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:create")),
):
    source = await _owned(source_id, user)
    if source.get("deleting"):
        raise HTTPException(409, "Website source is being deleted")
    if source.get("status") == "processing":
        raise HTTPException(409, "A crawl is already running")
    page = await get_page_manifest(source_id, page_id)
    if page is None:
        raise HTTPException(404, "Website page not found")

    page.update(
        suppressed_by_user=False,
        status="processing",
        last_error=None,
        updated_at=datetime.now(UTC).isoformat(),
    )
    await upsert_page_manifest(page)
    source["status"], source["last_error"], source["updated_at"] = (
        "processing",
        None,
        datetime.now(UTC).isoformat(),
    )
    await upsert_source_manifest(source)
    try:
        source["last_task_id"] = await _enqueue(source, user, task_service, page_id=page_id)
    except Exception:
        source["status"], source["updated_at"] = "active", datetime.now(UTC).isoformat()
        page.update(status="failed", last_error="Unable to start page re-sync")
        await upsert_page_manifest(page)
        await upsert_source_manifest(source)
        raise
    await upsert_source_manifest(source)
    return {"id": page_id, "status": page["status"], "task_id": source["last_task_id"]}
