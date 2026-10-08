"""Managed URL source API coverage with OpenSearch-only manifests."""

from unittest.mock import AsyncMock

import pytest

from connectors.url import api
from connectors.url.api import CreateSourceBody
from session_manager import User


def _source(**overrides) -> dict:
    values = {
        "id": "source-1",
        "owner_id": "owner-1",
        "name": "Documentation",
        "starting_url": "https://docs.example.com/",
        "crawl_settings": {"seed_url": "https://docs.example.com/"},
        "status": "active",
        "deleting": False,
    }
    values.update(overrides)
    return values


def _user(source: dict) -> User:
    return User(user_id=source["owner_id"], email="owner@example.com", name="Owner")


def test_create_source_body_keeps_change_detection_outside_crawl_spec():
    body = CreateSourceBody(
        name="Documentation",
        starting_url="https://docs.example.com/",
        change_detection="always_reingest",
    )

    assert body.change_detection == "always_reingest"
    assert "change_detection" not in body.spec().as_dict()


@pytest.mark.asyncio
async def test_create_source_persists_crawl_configuration_in_its_manifest(monkeypatch):
    persisted: list[dict] = []
    monkeypatch.setattr(
        api,
        "upsert_source_manifest",
        AsyncMock(side_effect=lambda source, **_: persisted.append(dict(source))),
    )
    monkeypatch.setattr(api, "_enqueue", AsyncMock(return_value="task-1"))
    source = _source()

    result = await api.create_source(
        CreateSourceBody(
            name="Documentation",
            starting_url="https://docs.example.com/",
            scope="site",
            change_detection="always_reingest",
        ),
        task_service=object(),
        user=_user(source),
    )

    assert persisted[0]["crawl_settings"]["scope"] == "site"
    assert persisted[0]["change_detection"] == "always_reingest"
    assert persisted[-1]["last_task_id"] == "task-1"
    assert result["last_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_create_source_rejects_duplicate_name_for_the_same_owner(monkeypatch):
    source = _source()
    monkeypatch.setattr(api, "list_source_manifests", AsyncMock(return_value=[source]))

    with pytest.raises(Exception, match="already exists") as error:
        await api.create_source(
            CreateSourceBody(name=" documentation ", starting_url="https://other.example.com/"),
            task_service=object(),
            user=_user(source),
        )

    assert getattr(error.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_page_sync_enqueues_a_manifest_scoped_processor(monkeypatch):
    source = _source()
    page = {
        "web_source_id": source["id"],
        "web_page_id": "page-1",
        "canonical_url": "https://docs.example.com/guide",
        "status": "disabled",
        "suppressed_by_user": True,
    }
    enqueue = AsyncMock(return_value="task-1")
    persist_page, persist_source = AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(api, "_enqueue", enqueue)
    monkeypatch.setattr(api, "get_page_manifest", AsyncMock(return_value=page))
    monkeypatch.setattr(api, "upsert_page_manifest", persist_page)
    monkeypatch.setattr(api, "upsert_source_manifest", persist_source)

    result = await api.sync_page(source["id"], "page-1", task_service=object(), user=_user(source))

    assert enqueue.await_args.kwargs["page_id"] == "page-1"
    assert page["suppressed_by_user"] is False
    assert page["status"] == "processing"
    persist_page.assert_awaited_once_with(page)
    assert result == {"id": "page-1", "status": "processing", "task_id": "task-1"}


@pytest.mark.asyncio
async def test_disabling_a_page_updates_manifests_and_removes_chunks(monkeypatch):
    source = _source()
    page = {
        "web_source_id": source["id"],
        "web_page_id": "page-1",
        "document_id": "web-page:source-1:page-1",
        "content_document_id": "document-1",
        "status": "active",
    }
    delete_chunks, persist_page, persist_source = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(api, "get_page_manifest", AsyncMock(return_value=page))
    monkeypatch.setattr(api, "delete_page_chunks", delete_chunks)
    monkeypatch.setattr(api, "upsert_page_manifest", persist_page)
    monkeypatch.setattr(api, "list_page_manifests", AsyncMock(return_value=[page]))
    monkeypatch.setattr(api, "upsert_source_manifest", persist_source)

    result = await api.delete_page(source["id"], "page-1", user=_user(source))

    assert result == {"id": "page-1", "status": "disabled"}
    delete_chunks.assert_awaited_once_with("document-1")
    assert page["status"] == "disabled"
    assert page["chunk_count"] == 0
    assert persist_source.await_args.kwargs["pages"] == [page]


@pytest.mark.asyncio
async def test_source_deletion_uses_manifests_without_a_database(monkeypatch):
    source = _source(status="processing", last_task_id="task-1")
    monkeypatch.setattr(api, "get_source_manifest", AsyncMock(return_value=source))
    monkeypatch.setattr(api, "list_page_manifests", AsyncMock(return_value=[{}, {}]))
    monkeypatch.setattr(api, "delete_source_chunks", AsyncMock())
    monkeypatch.setattr(api, "upsert_source_manifest", AsyncMock())
    task_service = type("TaskService", (), {"cancel_task": AsyncMock(return_value=True)})()

    result = await api.delete_source(source["id"], task_service=task_service, user=_user(source))

    assert result == {"deleted": True, "child_count": 2}
    task_service.cancel_task.assert_awaited_once_with(source["owner_id"], "task-1")
