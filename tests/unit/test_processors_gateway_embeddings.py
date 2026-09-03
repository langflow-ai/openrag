"""Ingest embeddings go through llm_gateway, not the agentd-patched client.

The patched client forwards only a dynamic `api_key` to LiteLLM, so an Azure
deployment died on "No API Base provided for Azure OpenAI LLM provider" the
moment `DISABLE_INGEST_WITH_LANGFLOW=true` routed ingestion through it. The
gateway passes the stored credentials explicitly.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models.processors import TaskProcessor
from services.llm_gateway import LlmGatewayError


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / "report.md"
    path.write_text("quarterly revenue")
    return path


def _build_processor(monkeypatch, *, gateway, embedding_provider):
    monkeypatch.setattr("services.llm_gateway.embeddings", gateway)
    monkeypatch.setattr("models.processors.clients", SimpleNamespace(opensearch=None))
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="text-embedding-3-small",
                embedding_provider=embedding_provider,
                chunk_size=None,
                chunk_overlap=None,
            )
        ),
    )
    monkeypatch.setattr(
        "services.document_service.chunk_texts_for_embeddings",
        lambda texts, max_tokens: [texts] if texts else [],
    )

    indexed: dict = {}

    class _Writer:
        async def index_chunks(self, context, chunks, *, final=False):
            indexed["context"] = context
            indexed["chunks"] = chunks

    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: SimpleNamespace()
        ),
        document_index_writer=_Writer(),
    )
    # A tripwire: reaching for the patched client is the bug being fixed.
    models_service = SimpleNamespace(
        get_litellm_model_name=AsyncMock(return_value="azure/text-embedding-3-small")
    )
    docling_service = SimpleNamespace(
        convert_file=AsyncMock(
            return_value={
                "origin": {
                    "binary_hash": "doc-hash",
                    "filename": "report.md",
                    "mimetype": "text/markdown",
                },
                "texts": [{"text": "quarterly revenue", "prov": [{"page_no": 1}]}],
                "tables": [],
            }
        )
    )
    processor = TaskProcessor(document_service, models_service, docling_service)
    processor.check_document_exists = AsyncMock(return_value=False)
    return processor, indexed


async def _run(processor, file_path):
    return await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="doc-hash",
        owner_user_id="user-1",
        jwt_token="Bearer token",
        ocr=False,
        picture_descriptions=False,
    )


@pytest.mark.asyncio
async def test_azure_ingest_routes_through_the_gateway_by_space_id(monkeypatch, source_file):
    """`space:{provider}:{model}` is the route, not the LiteLLM slash form.

    The gateway trusts the head as the provider rather than re-deriving it from
    a slash-name, and it is the id written next to the vector — so the field
    written and the field later queried cannot diverge.
    """
    gateway = AsyncMock(
        side_effect=lambda body: {"data": [{"embedding": [0.1, 0.2, 0.3]} for _ in body["input"]]}
    )
    processor, indexed = _build_processor(monkeypatch, gateway=gateway, embedding_provider="azure")

    result = await _run(processor, source_file)

    assert result["status"] == "indexed"
    gateway.assert_awaited_once()
    body = gateway.await_args.args[0]
    assert body["model"] == "space:azure:text-embedding-3-small"
    assert body["input"] == ["quarterly revenue"]
    # The chunk is indexed under the same provider it was embedded with.
    assert indexed["context"].embedding_provider == "azure"


@pytest.mark.asyncio
async def test_provider_failure_surfaces_a_sanitised_message(monkeypatch, source_file):
    """A credentials error must not reach the user as a stack trace."""
    gateway = AsyncMock(
        side_effect=LlmGatewayError(
            "No API Base provided for Azure OpenAI.", 400, detail="SECRET-UPSTREAM-BODY"
        )
    )
    processor, indexed = _build_processor(monkeypatch, gateway=gateway, embedding_provider="azure")

    result = await _run(processor, source_file)

    assert result == {"status": "error", "error": "No API Base provided for Azure OpenAI."}
    assert "SECRET" not in str(result)
    assert indexed == {}


@pytest.mark.asyncio
async def test_the_openai_dict_response_shape_is_unwrapped(monkeypatch, source_file):
    """`embeddings()` returns a dict; the old client returned objects."""
    gateway = AsyncMock(return_value={"data": [{"embedding": [0.5, 0.6, 0.7]}]})
    processor, indexed = _build_processor(monkeypatch, gateway=gateway, embedding_provider="openai")

    result = await _run(processor, source_file)

    assert result["status"] == "indexed"
    assert gateway.await_args.args[0]["model"] == "space:openai:text-embedding-3-small"
    assert indexed["chunks"][0].vector == [0.5, 0.6, 0.7]
