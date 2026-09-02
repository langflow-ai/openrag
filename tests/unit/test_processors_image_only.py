from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pictures", "chunk_size", "expected_result"),
    [
        ([{"prov": [{"page_no": 1}], "annotations": []}], None, "indexed"),
        ([{"prov": [{"page_no": 1}], "annotations": []}], 1, "indexed"),
        ([], None, "error"),
    ],
)
async def test_image_only_placeholder_succeeds_but_empty_document_fails(
    monkeypatch, pictures, chunk_size, expected_result
):
    embedding_create = AsyncMock(
        return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2, 0.3]}])
    )
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
                chunk_size=chunk_size,
                chunk_overlap=None,
            )
        ),
    )
    monkeypatch.setattr(
        "services.document_service.chunk_texts_for_embeddings",
        lambda texts, max_tokens: [texts] if texts else [],
    )

    user_client = SimpleNamespace()
    indexed: dict = {}

    class FakeDocumentIndexWriter:
        async def index_chunks(self, context, chunks, *, final=False):
            indexed["context"] = context
            indexed["chunks"] = chunks
            indexed["final"] = final

    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: user_client
        ),
        document_index_writer=FakeDocumentIndexWriter(),
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
                "pictures": pictures,
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

    if expected_result == "error":
        assert result == {
            "status": "error",
            "error": "No text content could be extracted from document",
        }
        embedding_create.assert_not_awaited()
        assert indexed == {}
        return

    assert result == {"status": "indexed", "id": "image-hash"}
    embedding_create.assert_awaited_once_with(
        model="text-embedding-3-small", input=["<!-- image -->"]
    )
    assert indexed["final"] is True
    assert len(indexed["chunks"]) == 1
    assert indexed["chunks"][0].text == "<!-- image -->"
    assert indexed["chunks"][0].page == 1
