"""Unit tests for the ingest-time embedding call in TaskProcessor.process_document_standard.

Mirrors tests/unit/test_processor_mapping_client.py's mocking approach.
Proves a Cohere-family embedding model (Bedrock's cohere.embed-multilingual-v3)
gets `input_type="search_document"` passed as a plain kwarg to
`.embeddings.create()` during ingestion - the counterpart to
test_search_service_bedrock_embedding.py's query-time "search_query" case.
"""

from types import SimpleNamespace

import pytest

from models.processors import TaskProcessor
from services.document_index_writer import DocumentIndexWriter


class _FakeModelsService:
    def __init__(self, formatted_model: str):
        self.formatted_model = formatted_model

    async def get_litellm_model_name(self, embedding_model, provider=None):
        return self.formatted_model


async def _run_ingest(
    monkeypatch,
    tmp_path,
    *,
    embedding_model: str,
    formatted_model: str,
    content: str = None,
    config_chunk_size: int = 1000,
):
    user_client = SimpleNamespace(search_calls=[])
    admin_client = SimpleNamespace(bulk_calls=[], refresh_calls=[])

    async def search(**kwargs):
        user_client.search_calls.append(kwargs)
        return {"_scroll_id": None, "hits": {"hits": []}}

    user_client.search = search

    class Indices:
        async def exists(self, *, index):
            return True

        async def refresh(self, *, index):
            admin_client.refresh_calls.append({"index": index})

    async def bulk(**kwargs):
        admin_client.bulk_calls.append(kwargs)
        return {"errors": False, "items": []}

    admin_client.indices = Indices()
    admin_client.bulk = bulk

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            return user_client

    embed_calls = []

    class EmbeddingClient:
        class Embeddings:
            async def create(self, model, input, **kwargs):
                embed_calls.append({"model": model, "input": input, **kwargs})
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in input]
                )

        embeddings = Embeddings()

    async def ensure_embedding_field_exists(client, model_name, index_name, dimensions):
        return f"chunk_embedding_{model_name}"

    monkeypatch.setattr(
        "config.settings.clients",
        SimpleNamespace(opensearch=admin_client, patched_embedding_client=EmbeddingClient()),
    )
    monkeypatch.setattr(
        "models.processors.clients",
        SimpleNamespace(opensearch=admin_client, patched_embedding_client=EmbeddingClient()),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    monkeypatch.setattr("models.processors.get_index_name", lambda: "documents")
    monkeypatch.setattr("services.document_service.get_embedding_model", lambda: embedding_model)
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="", chunk_size=config_chunk_size, chunk_overlap=200
            )
        ),
    )
    monkeypatch.setattr(
        "services.document_index_writer.ensure_embedding_field_exists",
        ensure_embedding_field_exists,
    )

    file_path = tmp_path / "doc.md"
    file_path.write_text(content if content is not None else "# Test\n\nhello world", encoding="utf-8")
    document_service = SimpleNamespace(
        session_manager=SessionManager(),
        document_index_writer=DocumentIndexWriter(opensearch_client=admin_client),
    )
    processor = TaskProcessor(
        document_service=document_service,
        models_service=_FakeModelsService(formatted_model),
        docling_service=None,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="file-1",
        owner_user_id="user-1",
        original_filename="doc.md",
        jwt_token="Bearer user-token",
        embedding_model=embedding_model,
    )

    assert result["status"] == "indexed"
    return embed_calls


class TestCohereModelGetsInputType:
    @pytest.mark.asyncio
    async def test_bedrock_cohere_model_passes_search_document_input_type(
        self, monkeypatch, tmp_path
    ):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert len(calls) == 1
        assert calls[0]["model"] == "bedrock/cohere.embed-multilingual-v3"
        assert calls[0]["input_type"] == "search_document"

    @pytest.mark.asyncio
    async def test_input_type_not_wrapped_in_extra_body(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert "extra_body" not in calls[0]


class TestNonCohereModelOmitsInputType:
    @pytest.mark.asyncio
    async def test_openai_model_does_not_get_input_type(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
        )

        assert len(calls) == 1
        assert "input_type" not in calls[0]


class TestBedrockCredentialsTravelPerCall:
    """Bedrock's keys are passed as litellm kwargs rather than exported to
    AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, which the AWS S3 connector reads
    as its credential fallback (connectors/aws_s3/auth.py)."""

    @staticmethod
    def _bedrock_config(access_key_id="", secret_access_key=""):
        return SimpleNamespace(
            providers=SimpleNamespace(
                bedrock=SimpleNamespace(
                    region="us-east-1",
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                )
            )
        )

    @pytest.mark.asyncio
    async def test_explicit_credentials_are_attached_to_the_embed_call(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: TestBedrockCredentialsTravelPerCall._bedrock_config(
                "AKIAEXAMPLE", "supersecret"
            ),
        )

        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert calls[0]["aws_access_key_id"] == "AKIAEXAMPLE"
        assert calls[0]["aws_secret_access_key"] == "supersecret"

    @pytest.mark.asyncio
    async def test_iam_role_mode_attaches_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: TestBedrockCredentialsTravelPerCall._bedrock_config(),
        )

        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert "aws_access_key_id" not in calls[0]
        assert "aws_secret_access_key" not in calls[0]

    @pytest.mark.asyncio
    async def test_non_bedrock_model_attaches_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: TestBedrockCredentialsTravelPerCall._bedrock_config(
                "AKIAEXAMPLE", "supersecret"
            ),
        )

        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
        )

        assert "aws_access_key_id" not in calls[0]


class TestBedrockChunkSizeCap:
    """Bedrock's Cohere Embed v3 hard-limits input to 512 tokens per text
    entry (CodeRabbit finding on PR #2064, confirmed real: AWS's own docs
    put the limit at 512, and litellm 1.84.0 doesn't chunk/truncate for you -
    an oversized chunk reaches Bedrock as-is and gets rejected with a 400).
    Every other provider's default is 8000, so without a Bedrock-specific
    cap, ingestion into a Bedrock-backed index would routinely fail on any
    chunk bigger than a couple of sentences."""

    @pytest.mark.asyncio
    async def test_oversized_chunk_is_split_below_the_512_token_limit(self, monkeypatch, tmp_path):
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        # One unbroken paragraph (no blank lines), well over the 512-token
        # cap. A large config_chunk_size keeps the earlier character-window
        # resplit from also shrinking this below 512 tokens on its own,
        # so only the max_tokens cap under test governs the outcome -
        # otherwise this would pass even with a broken/missing cap.
        long_text = "# Doc\n\n" + ("The quick brown fox jumps over the lazy dog. " * 200)
        assert len(encoding.encode(long_text)) > 512

        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
            content=long_text,
            config_chunk_size=100_000,
        )

        assert calls, "expected at least one embeddings.create call"
        for call in calls:
            for text in call["input"]:
                assert len(encoding.encode(text)) <= 512

    @pytest.mark.asyncio
    async def test_same_oversized_chunk_stays_above_512_tokens_for_openai(self, monkeypatch, tmp_path):
        """Regression guard: the new bedrock branch must not affect the
        existing 8000-token default other providers rely on - the same text
        that gets forced under 512 tokens for Bedrock is free to stay above
        it for OpenAI."""
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        # A large config_chunk_size keeps the earlier character-window
        # resplit from also shrinking this below 512 tokens, so only the
        # max_tokens cap under test governs the outcome.
        long_text = "# Doc\n\n" + ("The quick brown fox jumps over the lazy dog. " * 200)

        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="text-embedding-3-small",
            formatted_model="text-embedding-3-small",
            content=long_text,
            config_chunk_size=100_000,
        )

        assert any(len(encoding.encode(text)) > 512 for text in calls[0]["input"])


class TestQueryVsIngestInputTypeDiffer:
    @pytest.mark.asyncio
    async def test_ingest_uses_search_document_not_search_query(self, monkeypatch, tmp_path):
        calls = await _run_ingest(
            monkeypatch,
            tmp_path,
            embedding_model="cohere.embed-multilingual-v3",
            formatted_model="bedrock/cohere.embed-multilingual-v3",
        )

        assert calls[0]["input_type"] == "search_document"
        assert calls[0]["input_type"] != "search_query"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
