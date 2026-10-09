"""Cohere `input_type` and the per-model chunk cap for embeddings.

Cohere embed v3 models (Bedrock, OCI, Cohere) are asymmetric: a query embedded
as a `search_document` silently loses retrieval quality. They also reject any
single input over 512 tokens, far below the 8000 the ingest path assumes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import llm_gateway, provider_error_log
from services.langflow_file_service import LangflowFileService
from services.llm_gateway import LlmGatewayError, embeddings, max_embedding_input_tokens


def _cfg():
    return SimpleNamespace(
        providers=SimpleNamespace(),
        knowledge=SimpleNamespace(embedding_model="x", embedding_provider="openai"),
    )


def _capture_aembedding(monkeypatch, litellm_model, provider="bedrock"):
    captured: dict = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return {"data": [{"embedding": [0.1], "index": 0}]}

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    monkeypatch.setattr(
        llm_gateway, "resolve_call", lambda *a, **k: (litellm_model, provider, {"k": "v"})
    )
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("litellm_model", "provider", "interactive", "body_type", "expected"),
    [
        ("bedrock/cohere.embed-english-v3", "bedrock", True, None, "search_query"),
        ("bedrock/cohere.embed-english-v3", "bedrock", False, None, "search_document"),
        ("bedrock/cohere.embed-english-v3", "bedrock", True, "classification", "classification"),
        ("bedrock/cohere.embed-english-v3", "bedrock", True, "garbage", "search_query"),
        ("bedrock/cohere.embed-english-v3", "bedrock", False, ["x"], "search_document"),
        ("oci/cohere.embed-english-v3.0", "oci", True, None, "search_query"),
        ("oci/cohere.embed-english-v3.0", "oci", False, None, "search_document"),
        ("text-embedding-3-small", "openai", True, None, None),
        ("azure_ai/Cohere-embed-v3-english", "azure_ai", True, None, None),
        ("bedrock/amazon.titan-embed-text-v2:0", "bedrock", True, None, None),
    ],
)
async def test_embeddings_input_type(
    monkeypatch, litellm_model, provider, interactive, body_type, expected
):
    captured = _capture_aembedding(monkeypatch, litellm_model, provider)
    body = {
        "model": "m",
        "input": ["q"],
        "aws_secret_access_key": "leak",
        "api_base": "http://evil",
        "dimensions": 8,
    }
    if body_type:
        body["input_type"] = body_type

    await embeddings(body, config=_cfg(), interactive=interactive)

    assert captured.get("input_type") == expected
    assert captured["k"] == "v"
    # Nothing else from the request body is forwarded to LiteLLM.
    assert set(captured) <= {"model", "input", "k", "input_type"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("litellm_model", "provider"),
    [("oci/cohere.embed-english-v3.0", "oci"), ("bedrock/cohere.embed-english-v3", "bedrock")],
)
@pytest.mark.parametrize("count", [97, 200])
async def test_embeddings_are_split_to_the_provider_input_limit(
    monkeypatch, litellm_model, provider, count
):
    calls: list[list[str]] = []

    async def fake_aembedding(**kwargs):
        batch = kwargs["input"]
        calls.append(batch)
        return {
            "data": [{"embedding": [float(i)], "index": i} for i in range(len(batch))],
            "usage": {"prompt_tokens": len(batch), "total_tokens": len(batch)},
        }

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    monkeypatch.setattr(llm_gateway, "resolve_call", lambda *a, **k: (litellm_model, provider, {}))
    texts = [f"t{i}" for i in range(count)]

    result = await embeddings({"model": "m", "input": texts}, config=_cfg())

    assert [len(c) for c in calls] == [96] * (count // 96) + ([count % 96] if count % 96 else [])
    assert [t for c in calls for t in c] == texts
    assert [d["index"] for d in result["data"]] == list(range(count))
    assert [d["embedding"] for d in result["data"]] == [[float(i % 96)] for i in range(count)]
    assert result["usage"] == {"prompt_tokens": count, "total_tokens": count}


@pytest.mark.asyncio
async def test_providers_without_a_limit_are_not_split(monkeypatch):
    calls: list[int] = []

    async def fake_aembedding(**kwargs):
        calls.append(len(kwargs["input"]))
        return {"data": [{"embedding": [0.1], "index": i} for i in range(calls[-1])]}

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    monkeypatch.setattr(
        llm_gateway, "resolve_call", lambda *a, **k: ("text-embedding-3-small", "openai", {})
    )

    await embeddings({"model": "m", "input": ["x"] * 200}, config=_cfg())

    assert calls == [200]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("bedrock:cohere.embed-english-v3", 512),
        ("oci:cohere.embed-english-v3.0", 512),
        ("bedrock:no-such-embedding-model", None),
    ],
)
def test_max_embedding_input_tokens(model, expected):
    assert max_embedding_input_tokens(model) == expected


def _failing_hook_config(monkeypatch, exc, stored=None):
    class Enhancement:
        @staticmethod
        def litellm_runtime_kwargs(stored):
            raise exc

    monkeypatch.setattr("enhancements.providers.registry.get", lambda key: Enhancement)
    monkeypatch.setattr(
        llm_gateway,
        "resolve_call",
        lambda *a, **k: ("oci/cohere.embed-english-v3.0", "oci", {}),
    )
    provider_error_log.clear()
    return SimpleNamespace(
        providers=SimpleNamespace(
            credential_values=lambda key: {}, stored_credentials=lambda key: stored or {}
        )
    )


@pytest.mark.asyncio
async def test_runtime_hook_value_error_is_a_clean_503(monkeypatch):
    cfg = _failing_hook_config(monkeypatch, ValueError("No OCI identity is available here"))

    with pytest.raises(LlmGatewayError) as caught:
        await embeddings({"model": "m", "input": ["q"]}, config=cfg)

    assert caught.value.status_code == 503
    assert caught.value.message == "No OCI identity is available here"
    assert provider_error_log.latest_failure("oci", "embedding") == caught.value.message


@pytest.mark.asyncio
async def test_runtime_hook_other_errors_get_a_generic_503(monkeypatch):
    cfg = _failing_hook_config(monkeypatch, RuntimeError("secret-token-123 leaked"))

    with pytest.raises(LlmGatewayError) as caught:
        await embeddings({"model": "m", "input": ["q"]}, config=cfg)

    assert caught.value.status_code == 503
    assert "secret-token-123" not in caught.value.message
    assert "secret-token-123" in caught.value.detail
    assert provider_error_log.latest_failure("oci", "embedding") == caught.value.message


@pytest.mark.asyncio
async def test_runtime_hook_error_detail_is_redacted(monkeypatch):
    cfg = _failing_hook_config(
        monkeypatch, RuntimeError("bad key secret-token-123"), {"oci_key": "secret-token-123"}
    )

    with pytest.raises(LlmGatewayError) as caught:
        await embeddings({"model": "m", "input": ["q"]}, config=cfg)

    assert "secret-token-123" not in caught.value.detail


@pytest.mark.asyncio
async def test_runtime_hook_runs_off_the_event_loop(monkeypatch):
    import threading

    seen: list[int] = []

    class Enhancement:
        @staticmethod
        def litellm_runtime_kwargs(stored):
            seen.append(threading.get_ident())
            return {}

    monkeypatch.setattr("enhancements.providers.registry.get", lambda key: Enhancement)
    cfg = SimpleNamespace(
        providers=SimpleNamespace(
            credential_values=lambda key: {}, stored_credentials=lambda key: {}
        )
    )

    await llm_gateway._provider_runtime_kwargs("oci", cfg)

    assert seen
    assert seen != [threading.get_ident()]


@pytest.mark.asyncio
async def test_dimension_probe_is_not_interactive(monkeypatch):
    seen: dict = {}
    bodies: list = []

    async def fake_embeddings(body, **kwargs):
        seen.update(kwargs)
        bodies.append(body)
        return {"data": [{"embedding": [0.0] * 8}]}

    monkeypatch.setattr(llm_gateway, "embeddings", fake_embeddings)
    service = LangflowFileService(docling_service=AsyncMock())

    await service._detect_embedding_dimensions("cohere.embed-english-v3", "bedrock")

    assert [b["model"] for b in bodies] == ["bedrock:cohere.embed-english-v3"]
    assert seen.get("interactive") is False or "interactive" not in seen


@pytest.mark.asyncio
async def test_processors_cap_chunks_for_the_overridden_model_only(monkeypatch, tmp_path):
    """The cap follows the model of this call, not the configured default model."""
    import tiktoken

    from models import processors
    from models.processors import TaskProcessor

    # One ~900-token paragraph: process_text_file keeps it as a single chunk.
    text_file = tmp_path / "long.txt"
    text_file.write_text(" ".join(f"word{i}" for i in range(450)), encoding="utf-8")
    encoding = tiktoken.get_encoding("cl100k_base")
    assert len(encoding.encode(text_file.read_text(encoding="utf-8"))) > 800

    embedded: list[str] = []

    async def fake_embeddings(body, **_kwargs):
        embedded.extend(body["input"])
        return {"data": [{"embedding": [0.1]} for _ in body["input"]]}

    class Writer:
        async def index_chunks(self, context, chunks, *, final=False):
            return None

    monkeypatch.setattr("services.llm_gateway.embeddings", fake_embeddings)
    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: SimpleNamespace()
        ),
        document_index_writer=Writer(),
    )

    async def run(model, provider):
        embedded.clear()
        monkeypatch.setattr(
            processors,
            "get_openrag_config",
            lambda: SimpleNamespace(
                knowledge=SimpleNamespace(
                    embedding_model="text-embedding-3-small",
                    embedding_provider=provider,
                    chunk_size=None,
                    chunk_overlap=None,
                )
            ),
        )
        processor = TaskProcessor(
            document_service,
            SimpleNamespace(get_litellm_model_name=AsyncMock(return_value=model)),
            SimpleNamespace(),
        )
        processor.check_document_exists = AsyncMock(return_value=False)
        await processor.process_document_standard(
            file_path=str(text_file),
            file_hash="h",
            owner_user_id="u",
            jwt_token="Bearer t",
            embedding_model=model,
            ocr=False,
            picture_descriptions=False,
        )
        return list(embedded)

    capped = await run("cohere.embed-english-v3", "bedrock")
    assert len(capped) > 1
    assert all(len(encoding.encode(t)) <= 512 for t in capped)
    assert all(len(t) <= 1024 for t in capped)

    uncapped = await run("text-embedding-3-small", "openai")
    assert len(uncapped) == 1
    assert len(encoding.encode(uncapped[0])) > 800


class _Resp:
    status_code = 200
    reason_phrase = "OK"
    headers = {"content-type": "application/json"}
    text = "{}"

    def json(self):
        return {"status": "ok"}


def _langflow_service(monkeypatch, provider, chunk_size=4000):
    captured: dict = {}
    callback: dict = {}

    async def langflow_request(method, endpoint, **kwargs):
        captured.update(kwargs)
        return _Resp()

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "services.langflow_file_service.clients",
        SimpleNamespace(langflow_request=langflow_request),
    )
    monkeypatch.setattr("utils.langflow_headers.add_provider_credentials_to_headers", noop)
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="text-embedding-3-small",
                embedding_provider=provider,
                chunk_size=chunk_size,
                chunk_overlap=200,
            )
        ),
    )
    service = LangflowFileService(ingest_token_service=object())
    service._ensure_url_ingest_flow_id = AsyncMock(return_value="flow")

    def configure(**kwargs):
        callback.update(kwargs)
        return "tok", "run"

    service._configure_ingest_callback = configure
    service._ingest_callback_global_var_headers = lambda **kwargs: {}
    return service, captured, callback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [("bedrock", "cohere.embed-english-v3", 1024), ("openai", "text-embedding-3-small", 4000)],
)
async def test_run_ingestion_flow_caps_split_text(monkeypatch, provider, model, expected):
    service, captured, callback = _langflow_service(monkeypatch, provider)

    await service.run_ingestion_flow(
        file_paths=["/tmp/a.pdf"],
        file_tuples=[("a.pdf", b"x", "application/pdf")],
        selected_embedding_model=model,
    )

    assert callback["chunk_size"] == expected
    if expected == 4000:
        assert "chunk_size" not in captured["json"]["tweaks"].get("Split Text", {})
    else:
        assert captured["json"]["tweaks"]["Split Text"]["chunk_size"] == expected


@pytest.mark.asyncio
async def test_capping_split_text_also_clamps_the_overlap(monkeypatch):
    service, captured, callback = _langflow_service(monkeypatch, "bedrock")
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="cohere.embed-english-v3",
                embedding_provider="bedrock",
                chunk_size=4000,
                chunk_overlap=1500,
            )
        ),
    )

    await service.run_ingestion_flow(
        file_paths=["/tmp/a.pdf"],
        file_tuples=[("a.pdf", b"x", "application/pdf")],
    )

    split_text = captured["json"]["tweaks"]["Split Text"]
    assert (split_text["chunk_size"], split_text["chunk_overlap"]) == (1024, 204)
    assert (callback["chunk_size"], callback["chunk_overlap"]) == (1024, 204)


@pytest.mark.asyncio
async def test_run_url_ingestion_flow_caps_split_text(monkeypatch):
    service, captured, callback = _langflow_service(monkeypatch, "bedrock")
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model="cohere.embed-english-v3",
                embedding_provider="bedrock",
                chunk_size=4000,
                chunk_overlap=200,
            )
        ),
    )

    await service.run_url_ingestion_flow("https://example.com/docs", crawl_depth=1)

    assert callback["chunk_size"] == 1024
    assert captured["json"]["tweaks"]["Split Text"]["chunk_size"] == 1024
