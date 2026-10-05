"""Per-provider embedding bulkhead and the opaque upstream 502/504 message.

A folder upload fans out to several Langflow ingest runs, each embedding one
chunk per request on eight threads. Against a slow (CPU-served) RHOAI model
the calls queued at the endpoint until its kube-rbac-proxy timed them out with
a body-less 502. The gateway now bounds concurrent embedding calls per
provider (limit supplied by the provider enhancement) and explains such a 502.

One slot of that limit is reserved for query embeddings (`interactive=True`:
search and chat retrieval) so a bulk ingest cannot queue them; the two lanes
split the limit rather than add to it.
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


async def _embed_concurrently(cfg, model: str, count: int, *, interactive=False) -> None:
    await asyncio.gather(
        *(
            embeddings({"model": model, "input": f"chunk {i}"}, config=cfg, interactive=interactive)
            for i in range(count)
        )
    )


RHOAI = "rhoai"


@pytest.mark.asyncio
async def test_rhoai_embeddings_are_bounded_by_the_configured_limit(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("3"), RHOAI_MODEL, 10)

    assert len(tracker.calls) == 10
    # One of the three slots is held back for queries.
    assert tracker.peak == 2


@pytest.mark.asyncio
async def test_rhoai_embeddings_use_the_default_limit_when_unset(monkeypatch):
    from enhancements.providers.redhat.openshift_ai import DEFAULT_EMBEDDING_MAX_CONCURRENCY

    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config(), RHOAI_MODEL, 2 * DEFAULT_EMBEDDING_MAX_CONCURRENCY)

    assert tracker.peak == DEFAULT_EMBEDDING_MAX_CONCURRENCY - 1


@pytest.mark.asyncio
async def test_limit_zero_disables_the_bulkhead(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("0"), RHOAI_MODEL, 10)

    assert tracker.peak == 10
    assert RHOAI not in llm_gateway._embedding_limiters


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
async def test_a_changed_limit_resizes_the_limiter_in_place():
    first = llm_gateway._embedding_limiter("rhoai", _rhoai_config("2"))
    same = llm_gateway._embedding_limiter("rhoai", _rhoai_config("2"))
    changed = llm_gateway._embedding_limiter("rhoai", _rhoai_config("5"))

    # One limiter for the provider's lifetime, so its in-flight count survives.
    assert first is same is changed
    assert llm_gateway._embedding_limiters[RHOAI].limit == 5


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
# Interactive lane
# --------------------------------------------------------------------------


class _Gate:
    """A fake `litellm.aembedding` whose calls block until released."""

    def __init__(self):
        self.release = asyncio.Event()
        self.in_flight = 0
        self.peak = 0
        self.started: list[str] = []

    async def __call__(self, **kwargs):
        self.started.append(kwargs["input"][0] if isinstance(kwargs["input"], list) else "")
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await self.release.wait()
        finally:
            self.in_flight -= 1
        return {"object": "list", "data": [{"embedding": [0.1], "index": 0}]}


def _embed(cfg, text: str, *, interactive: bool = False) -> asyncio.Task:
    return asyncio.create_task(
        embeddings({"model": RHOAI_MODEL, "input": text}, config=cfg, interactive=interactive)
    )


@pytest.mark.asyncio
async def test_a_query_is_not_queued_behind_bulk_ingestion(monkeypatch):
    gate = _Gate()
    monkeypatch.setattr("litellm.aembedding", gate)
    cfg = _rhoai_config("4")

    bulk = [_embed(cfg, f"chunk {i}") for i in range(20)]
    await asyncio.sleep(0.01)
    assert gate.in_flight == 3  # the bulk lane is full, 17 chunks waiting

    query = _embed(cfg, "query", interactive=True)
    await asyncio.sleep(0.01)
    assert "query" in gate.started  # started ahead of every waiting chunk
    assert gate.in_flight == 4

    gate.release.set()
    await asyncio.gather(query, *bulk)
    assert gate.peak == 4  # never more than the operator's limit in total


@pytest.mark.asyncio
async def test_queries_are_bounded_by_their_own_lane(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await _embed_concurrently(_rhoai_config("4"), RHOAI_MODEL, 6, interactive=True)

    assert len(tracker.calls) == 6
    assert tracker.peak == 1
    assert llm_gateway._embedding_limiters[RHOAI].limit == 4


@pytest.mark.asyncio
async def test_a_limit_of_one_is_shared_by_queries_and_ingestion(monkeypatch):
    gate = _Gate()
    monkeypatch.setattr("litellm.aembedding", gate)
    cfg = _rhoai_config("1")

    chunk = _embed(cfg, "chunk")
    await asyncio.sleep(0.01)
    query = _embed(cfg, "query", interactive=True)
    await asyncio.sleep(0.01)

    # Splitting a single slot would exceed the limit, so the query waits.
    assert gate.started == ["chunk"]
    gate.release.set()
    await asyncio.gather(chunk, query)
    assert gate.peak == 1


@pytest.mark.asyncio
async def test_no_limit_throttles_neither_lane(monkeypatch):
    tracker = _InFlightTracker()
    monkeypatch.setattr("litellm.aembedding", tracker)

    await asyncio.gather(
        _embed_concurrently(_rhoai_config("0"), RHOAI_MODEL, 5),
        _embed_concurrently(_rhoai_config("0"), RHOAI_MODEL, 5, interactive=True),
    )

    assert tracker.peak == 10
    assert not llm_gateway._embedding_limiters


@pytest.mark.parametrize(
    ("limit", "interactive", "expected"),
    [
        (4, False, ("bulk", 3)),
        (4, True, ("interactive", 1)),
        (2, False, ("bulk", 1)),
        (2, True, ("interactive", 1)),
        (1, False, ("bulk", 1)),
        (1, True, ("bulk", 1)),
    ],
)
def test_lane_limits_split_the_configured_total(limit, interactive, expected):
    assert llm_gateway._lane_limit(limit, interactive) == expected


# --------------------------------------------------------------------------
# Limit changes while calls are in flight
# --------------------------------------------------------------------------


class _PerCallGate:
    """A fake `litellm.aembedding` whose calls are released one at a time."""

    def __init__(self):
        self.events: dict[str, asyncio.Event] = {}
        self.started: list[str] = []
        self.in_flight = 0

    def release(self, text: str) -> None:
        self.events.setdefault(text, asyncio.Event()).set()

    async def __call__(self, **kwargs):
        text = kwargs["input"][0]
        self.started.append(text)
        self.in_flight += 1
        try:
            await self.events.setdefault(text, asyncio.Event()).wait()
        finally:
            self.in_flight -= 1
        return {"object": "list", "data": [{"embedding": [0.1], "index": 0}]}


async def _settle() -> None:
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_lowered_limit_counts_calls_still_in_flight(monkeypatch):
    gate = _PerCallGate()
    monkeypatch.setattr("litellm.aembedding", gate)

    old = [_embed(_rhoai_config("3"), "old 1"), _embed(_rhoai_config("3"), "old 2")]
    await _settle()
    assert gate.in_flight == 2

    # Lowered to 2 (one bulk slot): the two old calls already exceed it.
    new = _embed(_rhoai_config("2"), "new")
    await _settle()
    assert "new" not in gate.started

    gate.release("old 1")
    await _settle()
    assert "new" not in gate.started  # one old call still holds the bulk share

    gate.release("old 2")
    await _settle()
    assert "new" in gate.started
    gate.release("new")
    await asyncio.gather(*old, new)


@pytest.mark.asyncio
async def test_a_raised_limit_admits_queued_calls_at_once(monkeypatch):
    gate = _PerCallGate()
    monkeypatch.setattr("litellm.aembedding", gate)

    calls = [_embed(_rhoai_config("2"), f"chunk {i}") for i in range(3)]
    await _settle()
    assert gate.in_flight == 1  # bulk share of a limit of 2

    llm_gateway._embedding_limiter("rhoai", _rhoai_config("4"))
    await _settle()
    assert gate.in_flight == 3  # no call had to finish first

    for i in range(3):
        gate.release(f"chunk {i}")
    await asyncio.gather(*calls)


@pytest.mark.asyncio
async def test_lowering_to_one_counts_a_query_from_the_interactive_lane(monkeypatch):
    gate = _PerCallGate()
    monkeypatch.setattr("litellm.aembedding", gate)

    query = _embed(_rhoai_config("3"), "query", interactive=True)
    await _settle()

    chunk = _embed(_rhoai_config("1"), "chunk")
    await _settle()
    assert gate.started == ["query"]

    gate.release("query")
    await _settle()
    assert gate.started == ["query", "chunk"]
    gate.release("chunk")
    await asyncio.gather(query, chunk)


@pytest.mark.asyncio
async def test_turning_the_limit_off_and_on_keeps_counting(monkeypatch):
    gate = _PerCallGate()
    monkeypatch.setattr("litellm.aembedding", gate)

    first = _embed(_rhoai_config("2"), "first")
    await _settle()
    unbounded = [_embed(_rhoai_config("0"), f"free {i}") for i in range(2)]
    await _settle()
    assert gate.in_flight == 3  # "0" switches the limit off

    late = _embed(_rhoai_config("2"), "late")
    await _settle()
    assert "late" not in gate.started  # the unbounded calls still count

    gate.release("first")
    gate.release("free 0")
    await _settle()
    assert "late" not in gate.started  # total is 1 but the bulk share (1) is used
    gate.release("free 1")
    await _settle()
    assert "late" in gate.started
    gate.release("late")
    await asyncio.gather(first, *unbounded, late)


@pytest.mark.asyncio
async def test_a_limit_of_one_hands_the_slot_to_a_waiting_query_first(monkeypatch):
    gate = _PerCallGate()
    monkeypatch.setattr("litellm.aembedding", gate)
    cfg = _rhoai_config("1")

    calls = [_embed(cfg, "chunk 0")]
    await _settle()
    calls += [_embed(cfg, "chunk 1"), _embed(cfg, "chunk 2")]
    await _settle()
    calls.append(_embed(cfg, "query", interactive=True))
    await _settle()

    gate.release("chunk 0")
    await _settle()
    assert gate.started == ["chunk 0", "query"]

    for text in ("query", "chunk 1", "chunk 2"):
        gate.release(text)
    await asyncio.gather(*calls)
    assert gate.started == ["chunk 0", "query", "chunk 1", "chunk 2"]


@pytest.mark.asyncio
async def test_a_slot_granted_to_a_cancelled_waiter_is_handed_on():
    limiter = llm_gateway._EmbeddingLimiter("rhoai", 1, asyncio.get_running_loop())
    await limiter.acquire(llm_gateway._BULK_LANE)

    waiter = asyncio.create_task(limiter.acquire(llm_gateway._BULK_LANE))
    await _settle()
    limiter.release(llm_gateway._BULK_LANE)  # grants the waiter's future...
    waiter.cancel()  # ...but it is cancelled before it resumes
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert limiter.in_flight == 0
    await asyncio.wait_for(limiter.acquire(llm_gateway._BULK_LANE), timeout=1)


@pytest.mark.asyncio
async def test_an_extra_release_does_not_free_a_phantom_slot():
    limiter = llm_gateway._EmbeddingLimiter("rhoai", 1, asyncio.get_running_loop())
    limiter.release(llm_gateway._BULK_LANE)

    await limiter.acquire(llm_gateway._BULK_LANE)
    waiter = asyncio.create_task(limiter.acquire(llm_gateway._BULK_LANE))
    await _settle()
    assert not waiter.done()  # the stray release did not leave a spare slot
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter


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
