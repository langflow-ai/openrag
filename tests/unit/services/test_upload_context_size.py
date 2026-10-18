"""Chat context uploads refuse an oversized file on the request the user is waiting for."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.docling_service import DoclingPayloadTooLarge
from services.document_service import DocumentService
from utils.upload_limits import (
    UploadTooLarge,
    docling_payload_too_large_message,
    docling_rejected_size_message,
    format_byte_size,
)


@pytest.mark.asyncio
async def test_process_upload_context_rejects_before_docling(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    upload = MagicMock()
    upload.read = AsyncMock(side_effect=[b"x" * (1024 * 1024 + 1), b""])
    docling = MagicMock()
    docling.convert_bytes = AsyncMock()

    service = DocumentService(docling_service=docling)

    with pytest.raises(UploadTooLarge, match="notes.pdf"):
        await service.process_upload_context(upload, filename="notes.pdf")

    docling.convert_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_upload_context_returns_413_for_a_size_refusal():
    from api import upload as upload_module

    class FakeUser:
        user_id = "alice"
        db_user_id = "db-alice"
        jwt_token = "token"
        name = "A"
        email = "a@x"

    document_service = MagicMock()
    document_service.process_upload_context = AsyncMock(
        side_effect=DoclingPayloadTooLarge(
            docling_rejected_size_message("notes.pdf", format_byte_size(2 * 1024 * 1024), 100),
            operator_detail=docling_payload_too_large_message(
                "notes.pdf",
                2 * 1024 * 1024,
                "https://docling-serve:5001/v1/convert/file/async",
            ),
        )
    )
    chat_service = MagicMock()
    chat_service.upload_context_chat = AsyncMock()

    response = await upload_module.upload_context(
        file=MagicMock(),
        previous_response_id=None,
        endpoint="chat",
        document_service=document_service,
        chat_service=chat_service,
        session_manager=None,
        user=FakeUser(),
    )

    assert response.status_code == 413
    assert b"notes.pdf" in response.body
    assert b"document-processing service" in response.body
    assert b"client_max_body_size" not in response.body
    assert b"docling-serve" not in response.body
    chat_service.upload_context_chat.assert_not_called()
