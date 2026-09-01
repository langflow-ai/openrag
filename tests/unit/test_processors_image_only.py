from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
async def test_placeholder_only_document_returns_no_text_error_before_embedding(monkeypatch):
    embedding_create = AsyncMock(side_effect=AssertionError("placeholder must not be embedded"))
    monkeypatch.setattr(
        "models.processors.clients",
        SimpleNamespace(
            opensearch=None,
            patched_embedding_client=SimpleNamespace(
                embeddings=SimpleNamespace(create=embedding_create)
            ),
        ),
    )
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="text-embedding-3-small",
                chunk_size=None,
                chunk_overlap=None,
            )
        ),
    )
    monkeypatch.setattr(
        "services.document_service.chunk_texts_for_embeddings",
        lambda texts, max_tokens: [texts],
    )

    user_client = SimpleNamespace()
    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: user_client
        )
    )
    models_service = SimpleNamespace(
        get_litellm_model_name=AsyncMock(return_value="text-embedding-3-small")
    )
    docling_service = SimpleNamespace(
        convert_file=AsyncMock(
            return_value={
                "origin": {
                    "binary_hash": "image-hash",
                    "filename": "scan.png",
                    "mimetype": "image/png",
                },
                "texts": [],
                "tables": [],
                "pictures": [{"prov": [{"page_no": 1}], "annotations": []}],
            }
        )
    )
    processor = TaskProcessor(document_service, models_service, docling_service)
    processor.check_document_exists = AsyncMock(return_value=False)

    result = await processor.process_document_standard(
        file_path="scan.png",
        file_hash="image-hash",
        owner_user_id="user-1",
        jwt_token="Bearer token",
        ocr=False,
        picture_descriptions=False,
    )

    assert result == {
        "status": "error",
        "error": "No text content could be extracted from document",
    }
    embedding_create.assert_not_awaited()
