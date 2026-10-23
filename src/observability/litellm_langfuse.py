"""LiteLLM's Langfuse OTel logger, without provider error text unless content capture is on.

``litellm.turn_off_message_logging`` redacts prompts and completions but not
failures: on a failed call LiteLLM records the exception (an ``exception``
event with its message and stack trace) and sets ``error.message`` and
``error.stack_trace`` from the provider's error text, which can echo the
prompt or the chunk being embedded. With capture off, those are dropped before
export; ``error.type`` and ``error.code`` stay. Our own spans already do the
same (``observability.spans``).

Imported only once tracing is enabled: it imports LiteLLM's OTel integration
and the OTel SDK.
"""

from typing import Any

from litellm.integrations.langfuse.langfuse_otel import LangfuseOtelLogger
from litellm.integrations.opentelemetry import OpenTelemetryConfig
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import Status

from observability.tracing import TRACING_CALLBACK

_ERROR_TEXT_ATTRIBUTES = frozenset({"error.message", "error.stack_trace"})
_EXCEPTION_EVENT = "exception"


def _without_error_text(span: ReadableSpan) -> ReadableSpan:
    """``span`` minus exception events, error message / stack trace and status text."""
    attributes = span.attributes or {}
    if (
        not _ERROR_TEXT_ATTRIBUTES.intersection(attributes)
        and not any(event.name == _EXCEPTION_EVENT for event in span.events)
        and not span.status.description
    ):
        return span
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes={k: v for k, v in attributes.items() if k not in _ERROR_TEXT_ATTRIBUTES},
        events=tuple(event for event in span.events if event.name != _EXCEPTION_EVENT),
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class _ErrorTextFilter(SpanProcessor):
    """Wraps LiteLLM's span processor; hands it ended spans without error text."""

    def __init__(self, inner: SpanProcessor):
        self._inner = inner

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        self._inner.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._inner.on_end(_without_error_text(span))

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class _RedactingLangfuseOtelLogger(LangfuseOtelLogger):
    """``LangfuseOtelLogger`` whose every span processor drops error text."""

    def _get_span_processor(self, *args: Any, **kwargs: Any) -> SpanProcessor:
        return _ErrorTextFilter(super()._get_span_processor(*args, **kwargs))


def build_langfuse_logger(*, capture_content: bool, exporter: Any = None) -> LangfuseOtelLogger:
    """The LiteLLM callback that exports gateway calls to Langfuse.

    ``exporter`` replaces the OTLP export to Langfuse (tests); otherwise the
    logger reads ``LANGFUSE_*`` from the environment like LiteLLM's own.
    """
    logger_class = LangfuseOtelLogger if capture_content else _RedactingLangfuseOtelLogger
    config = OpenTelemetryConfig(exporter=exporter) if exporter is not None else None
    # Registered under LiteLLM's own name for this integration, which keeps it
    # off the global tracer provider (``OpenTelemetry._skip_set_global``).
    return logger_class(config=config, callback_name=TRACING_CALLBACK)
