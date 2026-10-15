"""Tests for backend LLM tracing (`observability/tracing.py`).

Tracing is off by default, and when it is on, traces carry metadata only unless
content capture is explicitly opted into (twice, in SaaS). Both failure modes
are silent — tracing that never starts, or prompts and chunk text leaking into
Langfuse — so the gate and the redaction switch are pinned here.
"""

import pytest

from observability import tracing
from observability.tracing import TRACING_CALLBACK, configure_tracing, content_capture_enabled

_TRACING_ENV = (
    "OPENRAG_TRACING_ENABLED",
    "OPENRAG_TRACING_CAPTURE_CONTENT",
    "OPENRAG_TRACING_ALLOW_CONTENT_IN_SAAS",
    "OPENRAG_RUN_MODE",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_OTEL_HOST",
    "USE_OTEL_LITELLM_REQUEST_SPAN",
    "OTEL_TRACES_SAMPLER",
)


@pytest.fixture(autouse=True)
def _isolated_tracing(monkeypatch):
    """Clear tracing env and restore LiteLLM's process-global callback state."""
    import litellm

    for name in _TRACING_ENV:
        # setenv first so teardown restores the original value (or absence)
        # even when configure_tracing() writes the variable itself.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    # LiteLLM copies `callbacks` into these lists on first use and dedupes by
    # class, so a logger from one test would otherwise swallow the next test's.
    for name in (
        "callbacks",
        "input_callback",
        "success_callback",
        "failure_callback",
        "_async_success_callback",
        "_async_failure_callback",
    ):
        monkeypatch.setattr(litellm, name, [])
    monkeypatch.setattr(litellm, "turn_off_message_logging", False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")


def test_disabled_by_default_registers_no_callback(keys):
    import litellm

    assert configure_tracing() is False
    assert TRACING_CALLBACK not in litellm.callbacks


@pytest.mark.parametrize("value", ["false", "0", "", "no"])
def test_falsy_flag_registers_no_callback(monkeypatch, keys, value):
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", value)

    assert configure_tracing() is False
    assert TRACING_CALLBACK not in litellm.callbacks


def test_enabled_without_keys_warns_and_stays_off(monkeypatch, caplog):
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")
    warnings = []
    monkeypatch.setattr(tracing.logger, "warning", lambda msg, **kw: warnings.append(msg))

    assert configure_tracing() is False
    assert TRACING_CALLBACK not in litellm.callbacks
    assert any("LANGFUSE_PUBLIC_KEY" in w for w in warnings)


def test_enabled_with_keys_registers_langfuse_otel_callback(monkeypatch, keys):
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")

    assert configure_tracing() is True
    assert TRACING_CALLBACK in litellm.callbacks


def test_registration_is_idempotent(monkeypatch, keys):
    """Startup can run more than once in a process (tests, reloads)."""
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")

    configure_tracing()
    configure_tracing()

    assert litellm.callbacks.count(TRACING_CALLBACK) == 1


def test_enabled_redacts_message_content_by_default(monkeypatch, keys):
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")

    configure_tracing()

    assert litellm.turn_off_message_logging is True


def test_capture_opt_in_keeps_content_in_oss(monkeypatch, keys):
    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")
    monkeypatch.setenv("OPENRAG_TRACING_CAPTURE_CONTENT", "true")

    configure_tracing()

    assert litellm.turn_off_message_logging is False


@pytest.mark.parametrize(
    ("run_mode", "capture", "allow_saas", "expected"),
    [
        ("oss", "false", "false", False),
        ("oss", "true", "false", True),
        ("on_prem", "true", "false", True),
        ("saas", "true", "false", False),
        ("saas", "false", "true", False),
        ("saas", "true", "true", True),
    ],
)
def test_content_capture_policy(monkeypatch, run_mode, capture, allow_saas, expected):
    monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    monkeypatch.setenv("OPENRAG_TRACING_CAPTURE_CONTENT", capture)
    monkeypatch.setenv("OPENRAG_TRACING_ALLOW_CONTENT_IN_SAAS", allow_saas)

    assert content_capture_enabled() is expected


def test_saas_without_second_flag_redacts(monkeypatch, keys):
    import litellm

    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")
    monkeypatch.setenv("OPENRAG_TRACING_CAPTURE_CONTENT", "true")

    configure_tracing()

    assert litellm.turn_off_message_logging is True


def test_empty_host_targets_the_same_langfuse_cloud_as_langflow(monkeypatch, keys):
    """LiteLLM defaults to the US cloud; Langflow and the Langfuse SDK default to EU."""
    from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")

    configure_tracing()

    config = LangfuseOtelLogger.get_langfuse_otel_config()
    assert config.endpoint == "https://cloud.langfuse.com/api/public/otel"


def test_explicit_host_is_respected(monkeypatch, keys):
    from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.internal:3000")

    configure_tracing()

    config = LangfuseOtelLogger.get_langfuse_otel_config()
    assert config.endpoint == "http://langfuse.internal:3000/api/public/otel"


def test_missing_tracing_extra_warns_and_stays_off(monkeypatch, keys):
    import builtins

    import litellm

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")
    real_import = builtins.__import__

    def _no_otel_sdk(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk") or name.startswith("opentelemetry.exporter"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_otel_sdk)
    warnings = []
    monkeypatch.setattr(tracing.logger, "warning", lambda msg, **kw: warnings.append(msg))

    assert configure_tracing() is False
    assert TRACING_CALLBACK not in litellm.callbacks
    assert any("--extra tracing" in w for w in warnings)


# ── LiteLLM contract ───────────────────────────────────────────────────────
# Run real LiteLLM calls (mock_response, no network) through the Langfuse OTel
# logger with an in-memory exporter in place of OTLP. These pin the pinned
# LiteLLM's behaviour that tracing relies on: redaction, nesting under the
# caller's active span, and failures recorded on the span.

_SECRETS = ("SECRET-PROMPT", "SECRET-ANSWER", "SECRET-CHUNK")


@pytest.fixture
def traced(monkeypatch, keys):
    """Configure tracing, then swap the OTLP-exporting callback for an in-memory one."""
    import litellm
    from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
    from litellm.integrations.opentelemetry import OpenTelemetryConfig
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("OPENRAG_TRACING_ENABLED", "true")

    def _configure():
        assert configure_tracing() is True
        exporter = InMemorySpanExporter()
        logger = LangfuseOtelLogger(
            config=OpenTelemetryConfig(exporter=exporter), callback_name=TRACING_CALLBACK
        )
        litellm.callbacks = [logger if cb == TRACING_CALLBACK else cb for cb in litellm.callbacks]
        return exporter

    return _configure


@pytest.fixture
def caller_tracer():
    from opentelemetry.sdk.trace import TracerProvider

    return TracerProvider().get_tracer("openrag-test")


async def _drain(exporter, expected: int):
    """LiteLLM runs logging callbacks in the background; wait for the spans."""
    import asyncio

    for _ in range(100):
        spans = [s for s in exporter.get_finished_spans() if s.name == "litellm_request"]
        if len(spans) >= expected:
            return spans
        await asyncio.sleep(0.02)
    raise AssertionError(f"expected {expected} litellm_request spans, got {len(spans)}")


def _span_text(span) -> str:
    return repr(dict(span.attributes)) + repr([dict(e.attributes or {}) for e in span.events])


async def _completion(content="SECRET-PROMPT", response="SECRET-ANSWER"):
    import litellm

    return await litellm.acompletion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": content}],
        mock_response=response,
    )


async def _embedding():
    import litellm

    return await litellm.aembedding(
        model="openai/text-embedding-3-small", input=["SECRET-CHUNK"], mock_response=[0.1, 0.2]
    )


@pytest.mark.asyncio
async def test_gateway_calls_are_traced_without_content_by_default(traced):
    exporter = traced()

    await _completion()
    await _embedding()

    spans = await _drain(exporter, 2)
    assert {span.attributes["llm.model_name"] for span in spans} == {
        "gpt-4o-mini",
        "text-embedding-3-small",
    }
    for span in spans:
        assert not any(secret in _span_text(span) for secret in _SECRETS)


@pytest.mark.asyncio
async def test_content_is_traced_when_capture_is_opted_in(monkeypatch, traced):
    monkeypatch.setenv("OPENRAG_TRACING_CAPTURE_CONTENT", "true")
    exporter = traced()

    await _completion()

    (span,) = await _drain(exporter, 1)
    assert "SECRET-PROMPT" in _span_text(span)


@pytest.mark.asyncio
async def test_gateway_spans_nest_under_the_callers_active_span(traced, caller_tracer):
    """Ingest/search spans (03, 05) rely on this: no ids are threaded through call sites."""
    exporter = traced()

    with caller_tracer.start_as_current_span("ingest.embed") as parent:
        await _embedding()
        parent_ctx = parent.get_span_context()

    (span,) = await _drain(exporter, 1)
    assert span.context.trace_id == parent_ctx.trace_id
    assert span.parent.span_id == parent_ctx.span_id


@pytest.mark.asyncio
async def test_gateway_spans_survive_an_unsampled_foreign_parent(traced):
    """Instana's HTTP spans are active during requests and are never sampled.

    The SDK's default parent-based sampler would drop every LLM span beneath
    them, so Langfuse would see nothing whenever Instana is also enabled.
    """
    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    exporter = traced()
    instana_like = NonRecordingSpan(
        SpanContext(
            trace_id=0xD20FD29B103E15D2,
            span_id=0xD20FD29B103E15D2,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.DEFAULT),
        )
    )

    with trace.use_span(instana_like):
        await _embedding()

    (span,) = await _drain(exporter, 1)
    assert span.context.trace_id == 0xD20FD29B103E15D2


@pytest.mark.asyncio
async def test_failed_call_is_traced_with_the_error(traced):
    import litellm
    from opentelemetry.trace import StatusCode

    exporter = traced()

    with pytest.raises(litellm.InternalServerError):
        await _completion(response=Exception("upstream exploded"))

    (span,) = await _drain(exporter, 1)
    assert span.status.status_code is StatusCode.ERROR
    assert "error.type" in span.attributes
