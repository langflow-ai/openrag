"""Sync preview reports updates, not just deletions.

The preview endpoints feed the "Sync all connectors" confirmation dialog. They
used to return orphans only, so the dialog could describe deletions but had
nothing to say about modified files — it filled the gap with the *total synced
count*, which reads as "all N files will be updated" no matter how many actually
changed. These endpoints now return the changed files themselves.

`updates_available: false` means the connector cannot answer ahead of time (it
re-reads every file and decides during ingest), which the dialog must render
differently from "nothing will be updated".
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api import connectors as connectors_api


def _json(response):
    return json.loads(response.body.decode())


@pytest.fixture(autouse=True)
def _allow_all_connectors(monkeypatch):
    monkeypatch.setattr(connectors_api, "_connector_access_denied", AsyncMock(return_value=None))
    monkeypatch.setattr(
        connectors_api, "_allowed_connector_types_for_request", AsyncMock(return_value=["ibm_cos"])
    )


def _patch_preview(monkeypatch, preview):
    monkeypatch.setattr(
        connectors_api, "_preview_for_connector_type", AsyncMock(return_value=preview)
    )


def _user():
    return SimpleNamespace(user_id="alice", jwt_token="token")


@pytest.mark.asyncio
async def test_preview_returns_changed_files(monkeypatch):
    _patch_preview(
        monkeypatch,
        connectors_api.ConnectorSyncPreview(
            orphans=[{"document_id": "c::gone", "filename": "gone.pdf"}],
            updates=[{"document_id": "c::b", "filename": "b.pdf"}],
            synced_count=3,
        ),
    )

    response = await connectors_api.connector_sync_preview(
        "ibm_cos",
        MagicMock(),
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        user=_user(),
        session=MagicMock(),
    )

    body = _json(response)
    assert response.status_code == 200
    assert body["updates"] == [{"document_id": "c::b", "filename": "b.pdf"}]
    assert body["updates_available"] is True
    assert body["orphans"] == [{"document_id": "c::gone", "filename": "gone.pdf"}]
    assert body["orphans_available"] is True
    assert body["synced_count"] == 3


@pytest.mark.asyncio
async def test_preview_marks_updates_unavailable_for_replace_always_connectors(monkeypatch):
    """Unknowable is not the same as none — the dialog needs to tell them apart."""
    _patch_preview(
        monkeypatch,
        connectors_api.ConnectorSyncPreview(orphans=[], updates=None, synced_count=7),
    )

    response = await connectors_api.connector_sync_preview(
        "google_drive",
        MagicMock(),
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        user=_user(),
        session=MagicMock(),
    )

    body = _json(response)
    assert body["updates"] == []
    assert body["updates_available"] is False
    # The synced total is still reported, so the dialog can say "7 re-checked".
    assert body["synced_count"] == 7


@pytest.mark.asyncio
async def test_sync_all_preview_groups_updates_by_connector_type(monkeypatch):
    _patch_preview(
        monkeypatch,
        connectors_api.ConnectorSyncPreview(
            orphans=[],
            updates=[{"document_id": "c::b", "filename": "b.pdf"}],
            synced_count=4,
        ),
    )

    response = await connectors_api.connectors_sync_all_preview(
        MagicMock(),
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        user=_user(),
        session=MagicMock(),
    )

    body = _json(response)
    assert body["updates_by_type"] == {"ibm_cos": [{"document_id": "c::b", "filename": "b.pdf"}]}
    assert body["updates_available_by_type"] == {"ibm_cos": True}


@pytest.mark.asyncio
async def test_sync_all_preview_survives_a_failing_connector(monkeypatch):
    """A connector that blows up must not take the whole preview down."""
    monkeypatch.setattr(
        connectors_api,
        "_preview_for_connector_type",
        AsyncMock(side_effect=RuntimeError("listing exploded")),
    )

    response = await connectors_api.connectors_sync_all_preview(
        MagicMock(),
        connector_service=MagicMock(),
        session_manager=MagicMock(),
        user=_user(),
        session=MagicMock(),
    )

    assert response.status_code == 200
    body = _json(response)
    # Nothing synced and no orphans → the type is omitted entirely.
    assert body["updates_by_type"] == {}
    assert body["orphans_by_type"] == {}
