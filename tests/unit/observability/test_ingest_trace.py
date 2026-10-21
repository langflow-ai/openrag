"""One Langfuse trace per file on the non-Langflow ingest path (issue 03).

`process_document_standard` runs against fakes for Docling, the gateway and
OpenSearch; the spans go through the real Langfuse SDK into memory.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langfuse._client.attributes import LangfuseOtelSpanAttributes as LF
from opentelemetry import trace

from observability import spans
from observability.tracing import trace_context

STAGES = {
    "ingest.parse",
    "ingest.extract",
    "ingest.resplit",
    "ingest.token_cap",
    "ingest.embed",
    "ingest.index",
}


def _metadata(span, key):
    return span.attributes.get(f"{LF.OBSERVATION_METADATA}.openrag.{key}")


def _trace_metadata(span, key):
    return span.attributes.get(f"{LF.TRACE_METADATA}.openrag.{key}")


DOCLING_DOC = {
    "origin": {"filename": "report.pdf", "mimetype": "application/pdf"},
    "pages": {"1": {}, "2": {}},
    "texts": [
        {"text": "Intro paragraph", "prov": [{"page_no": 1}]},
        {"text": "Page two text", "prov": [{"page_no": 2}]},
        {"text": "More on two", "prov": [{"page_no": 2}]},
    ],
    "tables": [
        {
            "prov": [{"page_no": 2}],
            "data": {
                "table_cells": [
                    {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "text": "a"},
                ]
            },
        }
    ],
    "pictures": [{"prov": [{"page_no": 1}], "annotations": []}],
}


class _Pipeline:
    """`process_document_standard` with every external dependency faked."""

    def __init__(self, monkeypatch, *, exists=False, stale_ids=("doc-1_0", "doc-1_1")):
        from models import processors as processors_mod
        from models.processors import TaskProcessor
        from services import llm_gateway as gateway_mod
        from utils import opensearch_delete

        self.opensearch = AsyncMock()
        self.opensearch.exists = AsyncMock(return_value=exists)
        self.check_exists = exists

        document_service = MagicMock()
        document_service.session_manager.get_user_opensearch_client = MagicMock(
            return_value=self.opensearch
        )
        self.indexed: list = []

        class _Writer:
            async def index_chunks(writer_self, context, chunks, *, final=False):
                self.indexed.extend(chunks)

        document_service.document_index_writer = _Writer()

        models_service = MagicMock()
        models_service.get_litellm_model_name = AsyncMock(return_value="text-embedding-3-small")

        self.docling = MagicMock()
        self.docling.convert_file = AsyncMock(return_value=DOCLING_DOC)

        self.processor = TaskProcessor(
            document_service=document_service,
            models_service=models_service,
            docling_service=self.docling,
        )
        self.processor.check_document_exists = AsyncMock(return_value=exists)

        config = MagicMock()
        config.knowledge.embedding_model = "text-embedding-3-small"
        config.knowledge.embedding_provider = "openai"
        config.knowledge.chunk_size = None
        config.knowledge.chunk_overlap = None
        config.knowledge.ocr = True
        config.knowledge.picture_descriptions = False
        config.knowledge.table_structure = True
        monkeypatch.setattr(processors_mod, "get_openrag_config", lambda: config)
        monkeypatch.setattr(processors_mod, "get_index_name", lambda: "test-index")
        fake_clients = MagicMock()
        fake_clients.opensearch = AsyncMock()
        monkeypatch.setattr(processors_mod, "clients", fake_clients)

        async def _collect(*_args, **_kwargs):
            return list(stale_ids)

        async def _delete(*_args, **_kwargs):
            return None

        monkeypatch.setattr(opensearch_delete, "collect_visible_document_ids", _collect)
        monkeypatch.setattr(opensearch_delete, "delete_document_ids", _delete)

        self.embed_parents: list[str] = []
        self.embed_error: Exception | None = None

        async def _embeddings(body, **_kwargs):
            self.embed_parents.append(getattr(trace.get_current_span(), "name", None))
            if self.embed_error is not None:
                raise self.embed_error
            return {
                "data": [{"embedding": [0.1, 0.2, 0.3]} for _ in body["input"]],
                "usage": {"prompt_tokens": 5 * len(body["input"]), "total_tokens": 0},
            }

        monkeypatch.setattr(gateway_mod, "embeddings", _embeddings)

    async def run(self, path: str, **kwargs):
        defaults = {
            "file_hash": "doc-1",
            "owner_user_id": "user-1",
            "connector_type": "local",
            "file_size": 1234,
        }
        return await self.processor.process_document_standard(
            file_path=path, **{**defaults, **kwargs}
        )


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("First paragraph.\n\nSecond paragraph.")
    return str(path)


@pytest.fixture
def pdf_file(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-fake")
    return str(path)


# --- one trace per file ----------------------------------------------------


@pytest.mark.asyncio
async def test_an_indexed_text_file_is_one_trace_with_its_stages(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    with trace_context(session_id="task-1", attributes={"openrag.task_id": "task-1"}):
        result = await pipeline.run(text_file)

    assert result["status"] == "indexed"
    exported = finished()
    root = exported["ingest.file"]
    assert root.parent is None
    assert set(exported) == {
        "ingest.file",
        "ingest.parse",
        "ingest.token_cap",
        "ingest.embed",
        "ingest.index",
    }
    for name in set(exported) - {"ingest.file"}:
        assert exported[name].context.trace_id == root.context.trace_id

    assert root.attributes[LF.TRACE_USER_ID] == "user-1"
    assert root.attributes[LF.TRACE_SESSION_ID] == "task-1"
    assert "ingest_path:openrag" in root.attributes[LF.TRACE_TAGS]
    assert _trace_metadata(root, "task_id") == "task-1"
    assert _trace_metadata(root, "document_id") == "doc-1"
    assert _trace_metadata(root, "ingest_path") == "openrag"
    assert _trace_metadata(root, "connector_type") == "local"
    assert _trace_metadata(root, "embedding_model") == "text-embedding-3-small"
    assert _trace_metadata(root, "embedding_provider") == "openai"
    assert _trace_metadata(root, "run_mode") == "oss"
    assert _trace_metadata(root, "file.extension") == ".txt"
    assert _metadata(root, "status") == "indexed"
    assert _metadata(root, "chunks") == 1


@pytest.mark.asyncio
async def test_stage_counts_for_a_text_file(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(text_file)

    exported = finished()
    parse = exported["ingest.parse"]
    assert _metadata(parse, "parser") == "Text Parser"
    assert _metadata(parse, "chunks") == 1

    cap = exported["ingest.token_cap"]
    assert _metadata(cap, "max_tokens") == 8000
    assert _metadata(cap, "chunks_in") == 1
    assert _metadata(cap, "chunks_out") == 1

    embed = exported["ingest.embed"]
    assert _metadata(embed, "batches") == 1
    assert _metadata(embed, "inputs") == 1
    assert _metadata(embed, "vectors") == 1
    assert _metadata(embed, "dimensions") == 3
    assert _metadata(embed, "prompt_tokens") == 5

    index = exported["ingest.index"]
    assert _metadata(index, "stale_chunks_deleted") == 2
    assert _metadata(index, "chunks_indexed") == 1


@pytest.mark.asyncio
async def test_embedding_calls_nest_under_the_embed_stage(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(text_file)

    assert pipeline.embed_parents == ["ingest.embed"]


@pytest.mark.asyncio
async def test_docling_parse_and_extract_counts(monkeypatch, finished, pdf_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(pdf_file, ocr=None, picture_descriptions=True)

    exported = finished()
    parse = exported["ingest.parse"]
    assert _metadata(parse, "parser").startswith("Docling")
    assert _metadata(parse, "pages") == 2
    assert _metadata(parse, "texts") == 3
    assert _metadata(parse, "tables") == 1
    assert _metadata(parse, "pictures") == 1
    # Unset per-request options fall back to the knowledge config, as Docling does.
    assert _metadata(parse, "ocr") is True
    assert _metadata(parse, "picture_descriptions") is True
    assert _metadata(parse, "table_structure") is True

    extract = exported["ingest.extract"]
    assert _metadata(extract, "chunks") == 3
    assert _metadata(extract, "chunks_text") == 2
    assert _metadata(extract, "chunks_table") == 1
    assert _metadata(extract, "chunks_picture") is None


@pytest.mark.asyncio
async def test_resplit_records_its_window_and_counts(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(text_file, chunk_size=10, chunk_overlap=2)

    resplit = finished()["ingest.resplit"]
    assert _metadata(resplit, "chunk_size") == 10
    assert _metadata(resplit, "chunk_overlap") == 2
    assert _metadata(resplit, "chunks_in") == 1
    assert _metadata(resplit, "chunks_out") == 5


# --- short and failed traces ------------------------------------------------


@pytest.mark.asyncio
async def test_an_unchanged_file_is_a_short_trace_without_error(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch, exists=True)

    result = await pipeline.run(text_file)

    assert result == {"status": "unchanged", "id": "doc-1"}
    exported = finished()
    assert set(exported) == {"ingest.file"}
    root = exported["ingest.file"]
    assert _metadata(root, "status") == "unchanged"
    assert root.attributes.get(LF.OBSERVATION_LEVEL) != "ERROR"


@pytest.mark.asyncio
async def test_an_embedding_failure_marks_the_stage_and_the_trace(monkeypatch, finished, text_file):
    from services.llm_gateway import LlmGatewayError

    pipeline = _Pipeline(monkeypatch)
    pipeline.embed_error = LlmGatewayError("upstream said no", 502)

    with pytest.raises(LlmGatewayError):
        await pipeline.run(text_file)

    exported = finished()
    assert exported["ingest.embed"].attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    root = exported["ingest.file"]
    assert root.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert root.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "LlmGatewayError in ingest.embed"
    assert "ingest.index" not in exported


@pytest.mark.asyncio
async def test_a_document_without_text_marks_the_trace_failed(monkeypatch, finished, tmp_path):
    pipeline = _Pipeline(monkeypatch)
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")

    result = await pipeline.run(str(empty))

    assert result["status"] == "error"
    root = finished()["ingest.file"]
    assert root.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert root.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "NoEmbeddings"


# --- content policy ---------------------------------------------------------


@pytest.mark.asyncio
async def test_filename_is_left_out_unless_capture_is_on(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(text_file, original_filename="q3-salaries.txt")
    for span in finished().values():
        assert "q3-salaries" not in str(dict(span.attributes))

    monkeypatch.setattr(spans, "content_capture_enabled", lambda: True)
    await pipeline.run(text_file, original_filename="q3-salaries.txt")
    assert _metadata(finished()["ingest.file"], "filename") == "q3-salaries.txt"


@pytest.mark.asyncio
async def test_chunk_text_never_reaches_a_span(monkeypatch, finished, text_file):
    pipeline = _Pipeline(monkeypatch)

    await pipeline.run(text_file)

    for span in finished().values():
        assert "First paragraph" not in str(dict(span.attributes))


@pytest.mark.asyncio
async def test_untraced_ingest_behaves_the_same(monkeypatch, text_file):
    monkeypatch.setattr(spans, "_client", None)
    pipeline = _Pipeline(monkeypatch)

    result = await pipeline.run(text_file)

    assert result == {"status": "indexed", "id": "doc-1", "ingest_path": "openrag"}
    assert len(pipeline.indexed) == 1
