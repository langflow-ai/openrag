"""Ingest attaches a warning when text is in a language not selected for OCR."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.processors import LangflowFileProcessor, TaskProcessor
from models.tasks import FileTask, TaskStatus, UploadTask

KOREAN = "이 문서는 다국어 문서 테스트입니다. 이미지에 있는 텍스트를 정확하게 인식하세요."


def _config(*, ocr: bool, ocr_languages: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            ocr=ocr,
            ocr_languages=ocr_languages,
            picture_descriptions=False,
            embedding_model="text-embedding-3-small",
            embedding_provider="openai",
            chunk_size=None,
            chunk_overlap=None,
        )
    )


def _search_client(*texts: str) -> AsyncMock:
    client = AsyncMock()
    client.search.return_value = {"hits": {"hits": [{"_source": {"text": t}} for t in texts]}}
    return client


# -- Sampling indexed chunks ----------------------------------------------------


@pytest.mark.asyncio
async def test_sampled_chunks_in_an_unselected_language_warn(monkeypatch):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )
    client = _search_client(KOREAN)

    warning = await TaskProcessor()._indexed_ocr_language_warning("doc-1", client, ocr_enabled=True)

    assert "Korean" in warning
    body = client.search.await_args.kwargs["body"]
    assert body["query"] == {"term": {"document_id": "doc-1"}}
    assert body["_source"] == ["text"]


@pytest.mark.asyncio
async def test_connector_chunks_are_sampled_by_connector_file_id(monkeypatch):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )
    client = _search_client(KOREAN)

    await TaskProcessor()._indexed_ocr_language_warning(
        "file-9", client, ocr_enabled=True, field="connector_file_id"
    )

    # Matches check_document_exists: older indices mapped this field as text.
    query = client.search.await_args.kwargs["body"]["query"]
    assert {"term": {"connector_file_id.keyword": "file-9"}} in query["bool"]["should"]


@pytest.mark.asyncio
async def test_no_sampling_when_ocr_is_off():
    client = _search_client(KOREAN)

    warning = await TaskProcessor()._indexed_ocr_language_warning(
        "doc-1", client, ocr_enabled=False
    )

    assert warning is None
    client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_sample_never_fails_the_ingest(monkeypatch):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )
    client = AsyncMock()
    client.search.side_effect = RuntimeError("opensearch down")

    warning = await TaskProcessor()._indexed_ocr_language_warning("doc-1", client, ocr_enabled=True)

    assert warning is None


# -- Langflow upload path -------------------------------------------------------


def _langflow_processor(opensearch_client) -> LangflowFileProcessor:
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    langflow_file_service = MagicMock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(
        return_value={"status": "indexed", "id": "hash-1"}
    )
    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="user-1",
        jwt_token="Bearer user-token",
        allow_anonymous_delete=True,
    )
    # Not a duplicate before ingest; present after it.
    processor.check_document_exists = AsyncMock(return_value=False)
    processor.check_filename_exists = AsyncMock(side_effect=[False, True])
    return processor


async def _ingest(processor, tmp_path) -> FileTask:
    item = tmp_path / "scan.pdf"
    item.write_bytes(b"%PDF-1.4 dummy")
    file_task = FileTask(file_path=str(item))
    file_task.filename = "scan.pdf"
    await processor.process_item(UploadTask(task_id="t-1", total_files=1), str(item), file_task)
    return file_task


@pytest.mark.asyncio
async def test_langflow_upload_completes_with_language_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )
    monkeypatch.setattr("models.processors.clients", SimpleNamespace(opensearch=None))

    file_task = await _ingest(_langflow_processor(_search_client(KOREAN)), tmp_path)

    assert file_task.status == TaskStatus.COMPLETED
    assert file_task.result["status"] == "indexed"
    assert "Korean" in file_task.result["warning"]


@pytest.mark.asyncio
async def test_langflow_upload_without_foreign_text_has_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )
    monkeypatch.setattr("models.processors.clients", SimpleNamespace(opensearch=None))

    file_task = await _ingest(_langflow_processor(_search_client("Plain English.")), tmp_path)

    assert file_task.status == TaskStatus.COMPLETED
    assert "warning" not in file_task.result


# -- Standard (non-Langflow) path ---------------------------------------------


def _standard_processor(texts: list[str]) -> TaskProcessor:
    class _Writer:
        async def index_chunks(self, context, chunks, *, final=False):
            return None

    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: SimpleNamespace()
        ),
        document_index_writer=_Writer(),
    )
    docling_service = SimpleNamespace(
        convert_file=AsyncMock(
            return_value={
                "origin": {"binary_hash": "doc-hash", "filename": "scan.pdf"},
                "texts": [
                    {"text": text, "label": "text", "prov": [{"page_no": 1}]} for text in texts
                ],
                "tables": [],
                "pictures": [],
            }
        )
    )
    processor = TaskProcessor(
        document_service,
        SimpleNamespace(get_litellm_model_name=AsyncMock(return_value="text-embedding-3-small")),
        docling_service,
    )
    processor.check_document_exists = AsyncMock(return_value=False)
    return processor


@pytest.fixture
def _standard_path_stubs(monkeypatch):
    async def fake_embeddings(body, **_kwargs):
        return {"data": [{"embedding": [0.1, 0.2, 0.3]} for _ in body["input"]]}

    monkeypatch.setattr("services.llm_gateway.embeddings", fake_embeddings)
    monkeypatch.setattr("models.processors.clients", SimpleNamespace(opensearch=None))
    monkeypatch.setattr(
        "services.document_service.chunk_texts_for_embeddings",
        lambda texts, max_tokens: [texts] if texts else [],
    )


@pytest.mark.asyncio
async def test_standard_path_returns_language_warning(monkeypatch, _standard_path_stubs):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=True, ocr_languages=["en"]),
    )

    result = await _standard_processor([KOREAN]).process_document_standard(
        file_path="scan.pdf", file_hash="doc-hash", owner_user_id="user-1", jwt_token="t"
    )

    assert result["status"] == "indexed"
    assert "Korean" in result["warning"]


@pytest.mark.asyncio
async def test_standard_path_skips_the_check_when_ocr_is_off(monkeypatch, _standard_path_stubs):
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: _config(ocr=False, ocr_languages=["en"]),
    )

    result = await _standard_processor([KOREAN]).process_document_standard(
        file_path="scan.pdf", file_hash="doc-hash", owner_user_id="user-1", jwt_token="t"
    )

    assert result == {"status": "indexed", "id": "doc-hash"}
