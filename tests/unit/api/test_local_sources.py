from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.local_sources import download_local_source
from services.local_source_service import stage_local_source
from session_manager import User

DOCUMENT_ID = "abcdefghijklmnopqrstuvwx"
SOURCE_ID = f"{DOCUMENT_ID}.{'a' * 32}"


@pytest.fixture
def user():
    """Return an authenticated user for source download tests."""
    return User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )


@pytest.mark.asyncio
async def test_download_returns_visible_archived_source(tmp_path, monkeypatch, user):
    """Return an archived source when one of its chunks is visible."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    source = tmp_path / "inbox" / "message.eml"
    source.parent.mkdir()
    source.write_bytes(b"From: sender@example.com\n\nHello")
    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    staged.commit()

    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 1}}}
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = client

    response = await download_local_source(
        staged.source_id, session_manager=session_manager, user=user
    )

    assert response.path == staged.archived_path.resolve()
    assert response.media_type == "message/rfc822"
    assert response.headers["cache-control"] == "private, no-store"
    query = client.search.await_args.kwargs["body"]["query"]
    assert query["bool"]["filter"][1]["wildcard"]["source_url"]["value"] == (
        f"*/api/source-files/{staged.source_id}"
    )


@pytest.mark.asyncio
async def test_download_hides_source_not_visible_to_user(tmp_path, monkeypatch, user):
    """Hide an archived source when none of its chunks are visible."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 0}}}
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = client

    with pytest.raises(HTTPException) as exc_info:
        await download_local_source(SOURCE_ID, session_manager=session_manager, user=user)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_preview_returns_supported_source_inline(tmp_path, monkeypatch, user):
    """Serve supported source formats inline for the preview dialog."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    source = tmp_path / "inbox" / "report.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-preview")
    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    staged.commit()

    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 1}}}
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = client

    response = await download_local_source(
        staged.source_id,
        session_manager=session_manager,
        user=user,
        preview=True,
    )

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


@pytest.mark.asyncio
async def test_preview_rejects_active_content(tmp_path, monkeypatch, user):
    """Reject active source formats from inline preview rendering."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    source = tmp_path / "inbox" / "page.html"
    source.parent.mkdir()
    source.write_text("<script>alert('unsafe')</script>")
    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    staged.commit()

    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 1}}}
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = client

    with pytest.raises(HTTPException) as exc_info:
        await download_local_source(
            staged.source_id,
            session_manager=session_manager,
            user=user,
            preview=True,
        )

    assert exc_info.value.status_code == 415
