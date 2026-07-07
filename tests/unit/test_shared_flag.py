"""Unit tests for the shared COS ingestion flag."""

from typing import Any

import pytest

from models.processors import resolve_shared_owner_fields
from services.document_index_writer import (
    DocumentIndexChunk,
    DocumentIndexContext,
    DocumentIndexWriter,
)

# ---------------------------------------------------------------------------
# resolve_shared_owner_fields
# ---------------------------------------------------------------------------


def test_resolve_shared_owner_fields_private():
    result = resolve_shared_owner_fields("user-1", "Alice", "alice@example.com", shared=False)
    assert result == ("user-1", "Alice", "alice@example.com")


def test_resolve_shared_owner_fields_shared():
    result = resolve_shared_owner_fields("user-1", "Alice", "alice@example.com", shared=True)
    assert result == (None, "Anonymous User", "anonymous@localhost")


def test_resolve_shared_owner_fields_shared_none_inputs():
    result = resolve_shared_owner_fields(None, None, None, shared=True)
    assert result == (None, "Anonymous User", "anonymous@localhost")


def test_resolve_shared_owner_fields_private_none_inputs():
    result = resolve_shared_owner_fields(None, None, None, shared=False)
    assert result == (None, None, None)


# ---------------------------------------------------------------------------
# DocumentIndexWriter._build_chunk_document
# ---------------------------------------------------------------------------


def _make_context(**kwargs):
    defaults: dict[str, Any] = dict(
        document_id="doc-1",
        filename="test.pdf",
        mimetype="application/pdf",
        embedding_model="test-model",
        file_size=None,
        allowed_users=[],
        allowed_groups=[],
        allowed_principals=[],
        allowed_principal_labels=[],
        is_sample_data=False,
    )
    defaults.update(kwargs)
    return DocumentIndexContext(**defaults)


def _make_chunk():
    return DocumentIndexChunk(
        chunk_id="doc-1_0",
        text="hello world",
        vector=[0.1, 0.2, 0.3],
        page=1,
    )


def test_build_chunk_document_owner_present_when_set():
    writer = DocumentIndexWriter()
    context = _make_context(owner="user-1", owner_name="Alice", owner_email="alice@example.com")
    chunk = _make_chunk()
    doc = writer._build_chunk_document(
        context=context, chunk=chunk, embedding_field="vector", indexed_time="2026-01-01T00:00:00"
    )
    assert doc["owner"] == "user-1"
    assert doc["owner_name"] == "Alice"
    assert doc["owner_email"] == "alice@example.com"


def test_build_chunk_document_omits_owner_key_when_none():
    """Critical DLS test: owner key must be absent, not null, for must_not-exists-owner clause."""
    writer = DocumentIndexWriter()
    context = _make_context(owner=None, owner_name=None, owner_email=None)
    chunk = _make_chunk()
    doc = writer._build_chunk_document(
        context=context, chunk=chunk, embedding_field="vector", indexed_time="2026-01-01T00:00:00"
    )
    assert "owner" not in doc
    assert "owner_name" not in doc
    assert "owner_email" not in doc


def test_build_chunk_document_shared_has_anonymous_metadata():
    """Shared docs: owner key absent for DLS, owner_name/email set to anonymous values."""
    writer = DocumentIndexWriter()
    context = _make_context(
        owner=None, owner_name="Anonymous User", owner_email="anonymous@localhost"
    )
    chunk = _make_chunk()
    doc = writer._build_chunk_document(
        context=context, chunk=chunk, embedding_field="vector", indexed_time="2026-01-01T00:00:00"
    )
    assert "owner" not in doc
    assert doc["owner_name"] == "Anonymous User"
    assert doc["owner_email"] == "anonymous@localhost"


def test_build_chunk_document_allowed_users_always_present():
    """allowed_users/groups are always written (DLS lookup requires the field to exist)."""
    writer = DocumentIndexWriter()
    context = _make_context(owner=None)
    chunk = _make_chunk()
    doc = writer._build_chunk_document(
        context=context, chunk=chunk, embedding_field="vector", indexed_time="2026-01-01T00:00:00"
    )
    assert "allowed_users" in doc
    assert "allowed_groups" in doc


# ---------------------------------------------------------------------------
# build_replace_filename_query
# ---------------------------------------------------------------------------


def test_build_replace_filename_query_structure():
    """Must match filename AND (owner == user OR must_not-exists-owner)."""
    from utils.opensearch_queries import build_replace_filename_query

    q = build_replace_filename_query("report.pdf", "user-1")
    assert q["bool"]["filter"][0] == {"term": {"filename": "report.pdf"}}
    should = q["bool"]["filter"][1]["bool"]["should"]
    assert {"term": {"owner": "user-1"}} in should
    assert {"bool": {"must_not": {"exists": {"field": "owner"}}}} in should
    assert q["bool"]["filter"][1]["bool"]["minimum_should_match"] == 1


def test_build_replace_filename_query_differs_from_owned_query():
    """replace query is broader than the owner-only query."""
    from utils.opensearch_queries import build_owned_filename_query, build_replace_filename_query

    owned = build_owned_filename_query("f.pdf", "u")
    replace = build_replace_filename_query("f.pdf", "u")
    # owned has a single term filter; replace has a bool/should
    assert owned != replace


# ---------------------------------------------------------------------------
# ConnectorSyncBody Pydantic model
# ---------------------------------------------------------------------------


def test_connector_sync_body_defaults_shared_false():
    from api.connectors import ConnectorSyncBody

    body = ConnectorSyncBody()
    assert body.shared is False


def test_connector_sync_body_shared_true():
    from api.connectors import ConnectorSyncBody

    body = ConnectorSyncBody(shared=True)
    assert body.shared is True


def test_connector_sync_body_shared_backwards_compat():
    """Existing clients that omit shared get False."""
    from api.connectors import ConnectorSyncBody

    body = ConnectorSyncBody(selected_files=["file-1"])
    assert body.shared is False


# ---------------------------------------------------------------------------
# connector_sync guard: shared=True rejected for non-COS connectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_cos_connector_rejects_shared_true():
    """The API handler must return 400 when shared=True and connector_type != ibm_cos."""
    from unittest.mock import AsyncMock, MagicMock

    from api.connectors import ConnectorSyncBody, connector_sync

    body = ConnectorSyncBody(shared=True)
    connector_service = MagicMock()
    session_manager = MagicMock()
    user = MagicMock()
    user.jwt_token = "token"
    user.user_id = "user-1"

    # Stub out the connections lookup so the guard fires before any connector work
    connector_service.connection_manager.list_connections = AsyncMock(return_value=[])

    response = await connector_sync(
        connector_type="google_drive",
        body=body,
        connector_service=connector_service,
        session_manager=session_manager,
        user=user,
    )
    assert response.status_code == 400
    import json

    detail = json.loads(response.body)
    assert "ibm_cos" in detail["error"]


@pytest.mark.asyncio
async def test_ibm_cos_shared_true_does_not_hit_guard():
    """shared=True with ibm_cos should NOT be rejected by the guard."""
    from unittest.mock import AsyncMock, MagicMock

    from api.connectors import ConnectorSyncBody, connector_sync

    body = ConnectorSyncBody(shared=True)
    connector_service = MagicMock()
    session_manager = MagicMock()
    user = MagicMock()
    user.jwt_token = "token"
    user.user_id = "user-1"

    # Return empty active connections so we get 404 (not 400) — guard didn't fire
    connector_service.connection_manager.list_connections = AsyncMock(return_value=[])

    response = await connector_sync(
        connector_type="ibm_cos",
        body=body,
        connector_service=connector_service,
        session_manager=session_manager,
        user=user,
    )
    # 404 = "no active connections" error, not 400 = guard rejection
    assert response.status_code == 404
