"""One retry when a dead pooled connection eats a LiteLLM call.

LiteLLM keeps idle connections for 120s; vLLM (uvicorn) closes them after 5s.
A call that reuses one while the server's close is still in flight fails with
"Server disconnected" before the server reads it, and surfaced as a provider
failure in chat, search and the health banner. Reproduced against RHOAI through
`oc port-forward`, where every reuse 4.95-6.0s after the last call failed.
"""

from types import SimpleNamespace

import aiohttp
import httpx
import pytest

from api.provider_validation import _test_litellm_provider, is_provider_stale_connection_error
from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from services import llm_gateway, provider_error_log
from services.llm_gateway import LlmGatewayError, chat_completions, embeddings


def _stale_connection_error() -> Exception:
    """The chain LiteLLM 1.102 raises, as captured from a live RHOAI endpoint."""
    try:
        try:
            raise aiohttp.ServerDisconnectedError()
        except aiohttp.ServerDisconnectedError as disconnected:
            raise httpx.ReadError("Server disconnected") from disconnected
    except httpx.ReadError as read_error:
        error = Exception(
            "litellm.InternalServerError: InternalServerError: "
            "Hosted_vllmException - Server disconnected"
        )
        error.__cause__ = read_error
        return error


def _rhoai_config() -> SimpleNamespace:
    providers = ProvidersConfig(
        openai=OpenAIConfig(api_key="sk-openai", configured=True),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={
            "rhoai": GenericProviderConfig(
                credentials={
                    "api_base": "https://chat.example.com/v1",
                    "embedding_api_base": "https://embed.example.com/v1",
                    "api_key": "token",
                },
                configured=True,
            )
        },
    )
    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_model="granite-chat", llm_provider="rhoai"),
        knowledge=SimpleNamespace(embedding_model="granite-embedding", embedding_provider="rhoai"),
    )


class _FailsThenAnswers:
    """A fake LiteLLM call that raises the given errors in turn, then answers."""

    def __init__(self, answer, *errors: Exception):
        self.answer = answer
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.answer


EMBEDDING = {
    "object": "list",
    "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
    "usage": {"prompt_tokens": 1, "total_tokens": 1},
}
COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "choices": [{"message": {"role": "assistant", "content": "OK"}}],
}


@pytest.fixture(autouse=True)
def _clean_state():
    llm_gateway._embedding_limiters.clear()
    provider_error_log.clear()
    yield
    llm_gateway._embedding_limiters.clear()
    provider_error_log.clear()


# --- classification ---------------------------------------------------------


def test_litellm_wrapped_server_disconnect_is_a_stale_connection():
    assert is_provider_stale_connection_error(_stale_connection_error())


def test_httpx_disconnect_before_any_response_is_a_stale_connection():
    """LiteLLM's httpx transport, used when a provider hands it its own client."""
    error = httpx.RemoteProtocolError("Server disconnected without sending a response.")

    assert is_provider_stale_connection_error(error)


@pytest.mark.parametrize(
    "error",
    [
        # Sent after the response began: the server may have done the work.
        aiohttp.ClientPayloadError("Response payload is not completed"),
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
        httpx.ReadError("Server disconnected"),
        # Text alone is not evidence; only the transport's own type is.
        Exception("Server disconnected"),
        Exception("401 Unauthorized"),
        None,
    ],
    ids=["payload-cut", "body-cut", "bare-read-error", "text-only", "auth", "none"],
)
def test_other_failures_are_not_stale_connections(error):
    assert not is_provider_stale_connection_error(error)


# --- gateway ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_embedding_on_a_dead_connection_is_sent_again(monkeypatch):
    fake = _FailsThenAnswers(EMBEDDING, _stale_connection_error())
    monkeypatch.setattr("litellm.aembedding", fake)

    result = await embeddings(
        {"model": "rhoai:granite-embedding", "input": "q"}, config=_rhoai_config()
    )

    assert fake.calls == 2
    assert result["data"][0]["embedding"] == [0.1]
    assert provider_error_log.latest_failure("rhoai", "embedding") is None


@pytest.mark.asyncio
async def test_a_completion_on_a_dead_connection_is_sent_again(monkeypatch):
    fake = _FailsThenAnswers(COMPLETION, _stale_connection_error())
    monkeypatch.setattr("litellm.acompletion", fake)

    result = await chat_completions(
        {"model": "rhoai:granite-chat", "messages": [{"role": "user", "content": "hi"}]},
        config=_rhoai_config(),
    )

    assert fake.calls == 2
    assert result["choices"][0]["message"]["content"] == "OK"
    assert provider_error_log.latest_failure("rhoai", "chat") is None


@pytest.mark.asyncio
async def test_only_one_retry_is_made(monkeypatch):
    """A server that keeps dropping connections is a real failure, reported as one."""
    fake = _FailsThenAnswers(EMBEDDING, _stale_connection_error(), _stale_connection_error())
    monkeypatch.setattr("litellm.aembedding", fake)

    with pytest.raises(LlmGatewayError):
        await embeddings({"model": "rhoai:granite-embedding", "input": "q"}, config=_rhoai_config())

    assert fake.calls == 2
    assert provider_error_log.latest_failure("rhoai", "embedding") is not None


@pytest.mark.asyncio
async def test_other_failures_are_not_retried(monkeypatch):
    """The server may have acted on these; sending them again could double the work."""
    fake = _FailsThenAnswers(COMPLETION, httpx.ReadTimeout("timed out"))
    monkeypatch.setattr("litellm.acompletion", fake)

    with pytest.raises(LlmGatewayError):
        await chat_completions(
            {"model": "rhoai:granite-chat", "messages": [{"role": "user", "content": "hi"}]},
            config=_rhoai_config(),
        )

    assert fake.calls == 1


# --- health / pre-save probe -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["embedding", "chat"])
async def test_the_provider_probe_retries_a_dead_connection(monkeypatch, kind):
    """Otherwise a dead socket raises the health banner or blocks a settings save."""
    answer = EMBEDDING if kind == "embedding" else COMPLETION
    fake = _FailsThenAnswers(answer, _stale_connection_error())
    monkeypatch.setattr(f"litellm.a{'embedding' if kind == 'embedding' else 'completion'}", fake)

    await _test_litellm_provider(
        provider="rhoai",
        credentials={"api_base": "https://example.com/v1", "api_key": "token"},
        runtime_kwargs={},
        embedding_model="granite-embedding" if kind == "embedding" else None,
        llm_model="granite-chat" if kind == "chat" else None,
    )

    assert fake.calls == 2
