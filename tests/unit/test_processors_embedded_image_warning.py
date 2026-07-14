from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
async def test_standard_processor_warns_for_embedded_images_when_ocr_disabled(
    monkeypatch, tmp_path: Path
):
    from models import processors as processors_mod
    from services import document_service as document_service_mod

    user_client = AsyncMock()
    user_client.search = AsyncMock(return_value={"hits": {"hits": []}})
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)

    index_calls = []

    class FakeDocumentIndexWriter:
        async def index_chunks(self, context, chunks, *, final=False):
            index_calls.append({"context": context, "chunks": chunks, "final": final})
            return {"indexed_chunks": len(chunks)}

    document_service = SimpleNamespace(
        session_manager=session_manager,
        document_index_writer=FakeDocumentIndexWriter(),
    )
    models_service = MagicMock()
    models_service.get_litellm_model_name = AsyncMock(return_value="text-embedding-3-small")
    docling_service = MagicMock()
    docling_service.convert_file = AsyncMock(
        return_value={
            "origin": {
                "binary_hash": "doc-hash",
                "filename": "report.pdf",
                "mimetype": "application/pdf",
            },
            "texts": [{"text": "Selectable report text", "prov": [{"page_no": 1}]}],
            "tables": [],
            "pictures": [{"self_ref": "#/pictures/0", "prov": [{"page_no": 1}]}],
        }
    )

    fake_config = SimpleNamespace(
        knowledge=SimpleNamespace(embedding_model="text-embedding-3-small", ocr=False)
    )
    monkeypatch.setattr(processors_mod, "get_openrag_config", lambda: fake_config)
    monkeypatch.setattr(processors_mod, "get_index_name", lambda: "documents")
    monkeypatch.setattr(
        document_service_mod,
        "chunk_texts_for_embeddings",
        lambda texts, max_tokens=8000: [list(texts)],
    )

    class FakeEmbeddingClient:
        class Embeddings:
            async def create(self, model, input):
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    monkeypatch.setattr(
        processors_mod,
        "clients",
        SimpleNamespace(opensearch=AsyncMock(), patched_embedding_client=FakeEmbeddingClient()),
    )

    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")
    processor = TaskProcessor(
        document_service=document_service,
        models_service=models_service,
        docling_service=docling_service,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="doc-hash",
        owner_user_id="user-1",
        original_filename="report.pdf",
        jwt_token="jwt",
        ocr=False,
    )

    assert result["status"] == "indexed"
    assert "warning" in result
    assert "Embedded images were skipped" in result["warning"]
    assert len(index_calls) == 1


@pytest.mark.asyncio
async def test_standard_processor_does_not_warn_when_ocr_enabled(monkeypatch, tmp_path: Path):
    from models import processors as processors_mod
    from services import document_service as document_service_mod

    user_client = AsyncMock()
    user_client.search = AsyncMock(return_value={"hits": {"hits": []}})
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=user_client)

    class FakeDocumentIndexWriter:
        async def index_chunks(self, context, chunks, *, final=False):
            return {"indexed_chunks": len(chunks)}

    document_service = SimpleNamespace(
        session_manager=session_manager,
        document_index_writer=FakeDocumentIndexWriter(),
    )
    models_service = MagicMock()
    models_service.get_litellm_model_name = AsyncMock(return_value="text-embedding-3-small")
    docling_service = MagicMock()
    docling_service.convert_file = AsyncMock(
        return_value={
            "origin": {
                "binary_hash": "doc-hash",
                "filename": "report.pdf",
                "mimetype": "application/pdf",
            },
            "texts": [{"text": "Selectable report text", "prov": [{"page_no": 1}]}],
            "tables": [],
            "pictures": [{"self_ref": "#/pictures/0", "prov": [{"page_no": 1}]}],
        }
    )

    fake_config = SimpleNamespace(
        knowledge=SimpleNamespace(embedding_model="text-embedding-3-small", ocr=True)
    )
    monkeypatch.setattr(processors_mod, "get_openrag_config", lambda: fake_config)
    monkeypatch.setattr(processors_mod, "get_index_name", lambda: "documents")
    monkeypatch.setattr(
        document_service_mod,
        "chunk_texts_for_embeddings",
        lambda texts, max_tokens=8000: [list(texts)],
    )

    class FakeEmbeddingClient:
        class Embeddings:
            async def create(self, model, input):
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    monkeypatch.setattr(
        processors_mod,
        "clients",
        SimpleNamespace(opensearch=AsyncMock(), patched_embedding_client=FakeEmbeddingClient()),
    )

    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")
    processor = TaskProcessor(
        document_service=document_service,
        models_service=models_service,
        docling_service=docling_service,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="doc-hash",
        owner_user_id="user-1",
        original_filename="report.pdf",
        jwt_token="jwt",
        ocr=True,
    )

    assert result["status"] == "indexed"
    assert "warning" not in result
