"""LLM gateway: route OpenAI-shaped requests through LiteLLM using OpenRAG config."""

from types import SimpleNamespace

import pytest

from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from services.llm_gateway import (
    LlmGatewayError,
    chat_completions,
    embeddings,
    provider_credentials,
    resolve_call,
    split_model_id,
)


def _config(**overrides):
    providers = SimpleNamespace(
        openai=SimpleNamespace(api_key="sk-openai", configured=True),
        anthropic=SimpleNamespace(api_key="sk-ant", configured=True),
        ollama=SimpleNamespace(
            endpoint="http://localhost:11434", resolved_endpoint="", configured=True
        ),
        watsonx=SimpleNamespace(
            api_key="wx-key",
            endpoint="https://us-south.ml.cloud.ibm.com",
            project_id="proj",
            configured=True,
        ),
    )
    agent = SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai")
    knowledge = SimpleNamespace(
        embedding_model="text-embedding-3-small", embedding_provider="openai"
    )
    cfg = SimpleNamespace(providers=providers, agent=agent, knowledge=knowledge)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_split_model_id_recognises_known_prefixes():
    assert split_model_id("anthropic/claude-sonnet-4-5") == ("anthropic", "claude-sonnet-4-5")
    assert split_model_id("gpt-4o-mini") == (None, "gpt-4o-mini")
    assert split_model_id("openai/gpt-4o") == ("openai", "gpt-4o")


def test_resolve_call_uses_configured_provider_when_model_is_bare():
    model, provider, creds = resolve_call("gpt-4o-mini", kind="chat", config=_config())
    assert provider == "openai"
    assert model == "gpt-4o-mini"
    assert creds["api_key"] == "sk-openai"


def test_resolve_call_anthropic_gets_litellm_prefix():
    cfg = _config(agent=SimpleNamespace(llm_model="claude-sonnet-4-5", llm_provider="anthropic"))
    model, provider, creds = resolve_call(None, kind="chat", config=cfg)
    assert provider == "anthropic"
    assert model == "anthropic/claude-sonnet-4-5"
    assert creds["api_key"] == "sk-ant"


def test_resolve_call_watsonx_includes_project_and_endpoint():
    cfg = _config(
        knowledge=SimpleNamespace(embedding_model="ibm/slate", embedding_provider="watsonx")
    )
    model, provider, creds = resolve_call("ibm/slate", kind="embedding", config=cfg)
    assert provider == "watsonx"
    assert model == "watsonx/ibm/slate"
    assert creds["project_id"] == "proj"
    assert creds["api_base"] == "https://us-south.ml.cloud.ibm.com"


def test_provider_credentials_rejects_unknown_provider():
    with pytest.raises(LlmGatewayError) as exc:
        provider_credentials("gemini", _config())
    assert exc.value.status_code == 400
    assert "gemini" in exc.value.message


def test_provider_credentials_rejects_missing_openai_key():
    cfg = _config()
    cfg.providers.openai.api_key = ""
    with pytest.raises(LlmGatewayError) as exc:
        provider_credentials("openai", cfg)
    assert "not configured" in exc.value.message


def test_provider_credentials_supports_arbitrary_litellm_provider():
    providers = ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={
            "gemini": GenericProviderConfig(
                credentials={
                    "api_key": "gemini-secret",
                    "vertex_project": "project-1",
                },
                configured=True,
            )
        },
    )
    cfg = SimpleNamespace(providers=providers)

    assert provider_credentials("gemini", cfg) == {
        "api_key": "gemini-secret",
        "vertex_project": "project-1",
    }


@pytest.mark.asyncio
async def test_chat_completions_calls_litellm_with_config_key(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        }

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    result = await chat_completions(
        {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        config=_config(),
    )
    assert result["choices"][0]["message"]["content"] == "hi"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"] == "sk-openai"
    assert captured["messages"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_chat_completions_forwards_tools(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"id": "chatcmpl-1", "choices": []}

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    tools = [{"type": "function", "function": {"name": "search"}}]
    await chat_completions(
        {
            "model": "anthropic/claude-sonnet-4-5",
            "messages": [],
            "tools": tools,
            "tool_choice": "auto",
        },
        config=_config(),
    )
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"
    assert captured["model"] == "anthropic/claude-sonnet-4-5"
    assert captured["api_key"] == "sk-ant"


@pytest.mark.asyncio
async def test_chat_completions_stream_emits_sse(monkeypatch):
    class _Chunk:
        def model_dump_json(self):
            return '{"choices":[{"delta":{"content":"hi"}}]}'

    async def fake_stream():
        yield _Chunk()

    async def fake_acompletion(**kwargs):
        assert kwargs["stream"] is True
        return fake_stream()

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    stream = await chat_completions(
        {"model": "gpt-4o-mini", "messages": [], "stream": True},
        config=_config(),
    )
    lines = [line async for line in stream]
    assert lines[0].startswith("data: {")
    assert lines[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_chat_completions_redacts_api_key_on_failure(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("upstream rejected sk-openai")

    monkeypatch.setattr("litellm.acompletion", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await chat_completions({"model": "gpt-4o-mini", "messages": []}, config=_config())
    assert exc.value.status_code == 502
    assert "sk-openai" not in exc.value.message
    assert "[redacted]" in exc.value.message


@pytest.mark.asyncio
async def test_embeddings_calls_litellm(monkeypatch):
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return {"object": "list", "data": [{"embedding": [0.1], "index": 0}]}

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    result = await embeddings(
        {"model": "text-embedding-3-small", "input": ["hello"]},
        config=_config(),
    )
    assert result["data"][0]["embedding"] == [0.1]
    assert captured["api_key"] == "sk-openai"
    assert captured["input"] == ["hello"]
