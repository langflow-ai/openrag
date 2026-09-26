"""Per-provider embedding bulkhead and the opaque upstream 502/504 message.

A folder upload fans out to several Langflow ingest runs, each embedding one
chunk per request on eight threads. Against a slow (CPU-served) RHOAI model
the calls queued at the endpoint until its kube-rbac-proxy timed them out with
a body-less 502. The gateway now bounds concurrent embedding calls per
provider (limit supplied by the provider enhancement) and explains such a 502.
"""

import asyncio
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
from services import llm_gateway
from services.llm_gateway import LlmGatewayError, embeddings

RHOAI_MODEL = "rhoai:granite-embedding"


def _rhoai_config(limit: str | None = None) -> SimpleNamespace:
    credentials = {
        "api_base": "https://chat.example.com/v1",
        "embedding_api_base": "https://embed.example.com/v1",
        "api_key": "token",
    }
    if limit is not None:
        credentials["embedding_max_concurrency"] = limit
    providers = ProvidersConfig(
        openai=OpenAIConfig(api_key="sk-openai", configured=True),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={"rhoai": GenericProviderConfig(credentials=credentials, configured=True)},
    )
    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai"),
        knowledge=SimpleNamespace(embedding_model="granite-embedding", embedding_provider="rhoai"),
    )


class _InFlightTracker:
    """A fake `litellm.aembedding` that records peak concurrency."""

    def __init__(self, delay: float = 0.01):
        self.delay = delay
        self.in_flight = 0
        self.peak = 0
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        return {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }


@pytest.fixture(autouse=True)
def _reset_limiters():
    llm_gateway._embedding_limiters.clear()
    yield
    llm_gateway._embedding_limiters.clear()


async def _embed_concurrently(cfg, model: str, count: int) -> None:
    await asyncio.gather(
        *(embeddings({"model": model, "input": f"chunk {i}"}, config=cfg) for i in range(count))
    )


@pytest.mark.asyncio
async def test_rhoai_embeddings_are_bounded_by_the_configured_limit(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("2"), RHOAI_MODEL, 10)

    assert len(tracker.calls) == 10
    assert tracker.peak == 2


@pytest.mark.asyncio
async def test_rhoai_embeddings_use_the_default_limit_when_unset(monkeypatch):
    from enhancements.providers.redhat.openshift_ai import DEFAULT_EMBEDDING_MAX_CONCURRENCY

    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config(), RHOAI_MODEL, 12)

    assert tracker.peak == DEFAULT_EMBEDDING_MAX_CONCURRENCY


@pytest.mark.asyncio
async def test_limit_zero_disables_the_bulkhead(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("0"), RHOAI_MODEL, 10)

    assert tracker.peak == 10
    assert "rhoai" not in llm_gateway._embedding_limiters


@pytest.mark.asyncio
async def test_the_limit_never_reaches_litellm(monkeypatch):
    tracker = _InFlightTracker(delay=0)
    monkeypatch.setattr("litellm.aembedding", tracker)

    await embeddings({"model": RHOAI_MODEL, "input": "x"}, config=_rhoai_config("3"))

    assert "embedding_max_concurrency" not in tracker.calls[0]
    assert tracker.calls[0]["api_base"] == "https://embed.example.com/v1"


@pytest.mark.asyncio
async def test_providers_without_an_enhancement_are_unbounded(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("1"), "openai:text-embedding-3-small", 6)

    assert tracker.peak == 6
    assert "openai" not in llm_gateway._embedding_limiters


@pytest.mark.asyncio
async def test_a_changed_limit_rebuilds_the_limiter():
    first = llm_gateway._embedding_limiter("rhoai", _rhoai_config("2"))
    same = llm_gateway._embedding_limiter("rhoai", _rhoai_config("2"))
    changed = llm_gateway._embedding_limiter("rhoai", _rhoai_config("5"))

    assert first is same
    assert changed is not first
    assert llm_gateway._embedding_limiters["rhoai"][0] == 5


@pytest.mark.asyncio
async def test_a_cancelled_waiter_releases_its_slot(monkeypatch):
    gate = asyncio.Event()

    async def blocking_aembedding(**kwargs):
        await gate.wait()
        return {"object": "list", "data": [{"embedding": [0.1], "index": 0}]}

    monkeypatch.setattr("litellm.aembedding", blocking_aembedding)
    cfg = _rhoai_config("1")

    holder = asyncio.create_task(embeddings({"model": RHOAI_MODEL, "input": "a"}, config=cfg))
    waiter = asyncio.create_task(embeddings({"model": RHOAI_MODEL, "input": "b"}, config=cfg))
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    gate.set()
    await holder

    # Both slots are free again: a new call proceeds immediately.
    result = await asyncio.wait_for(
        embeddings({"model": RHOAI_MODEL, "input": "c"}, config=cfg), timeout=1
    )
    assert result["data"]


@pytest.mark.asyncio
async def test_a_failing_call_releases_its_slot(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("litellm.aembedding", boom)
    cfg = _rhoai_config("1")
    for _ in range(3):
        with pytest.raises(LlmGatewayError):
            await asyncio.wait_for(
                embeddings({"model": RHOAI_MODEL, "input": "x"}, config=cfg), timeout=1
            )


# --------------------------------------------------------------------------
# Opaque upstream 502/504
# --------------------------------------------------------------------------


class _FakeLiteLLMError(Exception):
    """Stands in for a LiteLLM exception, which is always provider-attributable."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.llm_provider = "hosted_vllm"
        self.status_code = status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 504])
async def test_an_empty_upstream_gateway_failure_gets_an_actionable_message(monkeypatch, status):
    async def boom(**kwargs):
        raise _FakeLiteLLMError(
            "litellm.BadGatewayError: BadGatewayError: Hosted_vllmException - ", status
        )

    monkeypatch.setattr("litellm.aembedding", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await embeddings({"model": RHOAI_MODEL, "input": "x"}, config=_rhoai_config())

    assert exc.value.message.startswith(llm_gateway._UPSTREAM_GATEWAY_MESSAGE)
    assert "(rhoai/granite-embedding)" in exc.value.message
    assert "Hosted_vllmException" not in exc.value.message
    assert exc.value.status_code == status


@pytest.mark.asyncio
async def test_a_gateway_failure_with_provider_text_keeps_that_text(monkeypatch):
    async def boom(**kwargs):
        raise _FakeLiteLLMError(
            "litellm.BadGatewayError: BadGatewayError: upstream connect error", 502
        )

    monkeypatch.setattr("litellm.aembedding", boom)
    with pytest.raises(LlmGatewayError) as exc:
        await embeddings({"model": RHOAI_MODEL, "input": "x"}, config=_rhoai_config())

    assert "upstream connect error" in exc.value.message
    assert llm_gateway._UPSTREAM_GATEWAY_MESSAGE not in exc.value.message


def test_an_empty_non_gateway_failure_is_not_relabelled():
    exc = _FakeLiteLLMError("litellm.InternalServerError: Hosted_vllmException - ", 500)
    message = llm_gateway._upstream_client_message(str(exc), "rhoai", "m", exc)
    assert llm_gateway._UPSTREAM_GATEWAY_MESSAGE not in message
