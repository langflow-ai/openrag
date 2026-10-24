"""OpenRAG's own spans in Langfuse: one trace per ingested file or search.

The gateway's model calls are traced by LiteLLM (see ``observability.tracing``);
these are the spans around them. LiteLLM parents each call under the active
OTel span, so an embedding call made inside an ``ingest.embed`` span nests
there in Langfuse.

Built on the Langfuse SDK with a private TracerProvider. Left to itself the SDK
installs its provider as the global one — or, with Instana's already global,
attaches its exporter to Instana's and ships every APM span to Langfuse.

Values recorded with ``Span.set`` are ids, counts and settings, sent whatever
the content setting; anything that can carry user content (filenames, query
text, exception messages) goes through ``Span.set_content`` or is dropped
unless content capture is on. When tracing is off every helper is a no-op.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from config.settings import get_langfuse_host
from observability.tracing import content_capture_enabled, current_trace_context, trace_context
from utils.run_mode_utils import get_run_mode

# Langfuse client our spans export through; None while tracing is off.
_client: Any = None

_PREFIX = "openrag."
# Attribute on an exception naming the innermost span it failed in, so the
# root can say where the trace failed.
_FAILED_SPAN_ATTR = "_openrag_failed_span"


def init_span_client(*, span_exporter: Any = None) -> None:
    """Create the Langfuse client for our spans. Called by ``configure_tracing``.

    ``span_exporter`` replaces the OTLP export to Langfuse (tests).
    """
    from langfuse import Langfuse
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    global _client
    _client = Langfuse(
        base_url=get_langfuse_host(),
        tracer_provider=TracerProvider(
            # Not parent-based: a background ingest runs inside the request's
            # (possibly unsampled Instana) context. Roots detach from it anyway.
            sampler=ALWAYS_ON,
            resource=Resource.create({"service.name": "openrag-backend"}),
        ),
        span_exporter=span_exporter,
    )


def _prefixed(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key if key.startswith(_PREFIX) else f"{_PREFIX}{key}": value
        for key, value in attributes.items()
        if value is not None
    }


class Span:
    """Handle on one of our spans; every method is a no-op while tracing is off."""

    def __init__(self, observation: Any = None):
        self._observation = observation

    def set(self, **attributes: Any) -> None:
        """Record ids, counts and settings as ``openrag.*`` metadata. Never content."""
        if self._observation is None:
            return
        values = _prefixed(attributes)
        if values:
            self._observation.update(metadata=values)

    def set_content(self, **attributes: Any) -> None:
        """Record values that can carry user content, only when capture is on."""
        if content_capture_enabled():
            self.set(**attributes)

    def fail(self, error_type: str, message: str | None = None) -> None:
        """Mark the span failed. ``message`` is content and kept only when capture is on."""
        if self._observation is None:
            return
        status = f"{error_type}: {message}" if message and content_capture_enabled() else error_type
        self._observation.update(level="ERROR", status_message=status)
        self.set(error_type=error_type)


_NOOP = Span()


@contextmanager
def _observe(name: str, attributes: Mapping[str, Any]) -> Iterator[Span]:
    """One Langfuse span, current for the block; failures recorded without their text.

    The SDK's span records an escaping exception with its message and stack
    trace, which can carry file paths or document text. So the exception is
    caught inside the span, recorded by type, and re-raised once it has ended.
    """
    error: BaseException | None = None
    metadata = _prefixed(attributes) or None
    with _client.start_as_current_observation(name=name, as_type="span", metadata=metadata) as obs:
        span = Span(obs)
        try:
            yield span
        except BaseException as exc:
            error = exc
            failed_in = getattr(exc, _FAILED_SPAN_ATTR, None)
            error_type = type(exc).__name__
            if failed_in is None:
                span.fail(error_type, str(exc))
                try:
                    setattr(exc, _FAILED_SPAN_ATTR, name)
                except AttributeError:
                    pass
            else:
                span.fail(f"{error_type} in {failed_in}", str(exc))
    if error is not None:
        raise error


@contextmanager
def trace_root(
    name: str,
    *,
    attributes: Mapping[str, Any],
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
) -> Iterator[Span]:
    """Start a new Langfuse trace named ``name`` for the block.

    Always a new trace, never a child of whatever span is current: background
    work inherits the request's context, whose span (Instana's) never reaches
    Langfuse. ``attributes`` become trace metadata on every span in the trace,
    together with the current ``trace_context``'s; user and session default
    to the context's too. Gateway calls made inside are labelled the same way.
    """
    if _client is None:
        yield _NOOP
        return

    from langfuse import propagate_attributes
    from opentelemetry import context as otel_context

    context = current_trace_context()
    user_id = user_id or context.get("user_id")
    session_id = session_id or context.get("session_id")
    trace_attributes = {
        **context.get("attributes", {}),
        "openrag.run_mode": get_run_mode(),
        **_prefixed(attributes),
    }

    token = otel_context.attach(otel_context.Context())
    try:
        with (
            _observe(name, {}) as root,
            propagate_attributes(
                trace_name=name,
                user_id=user_id or None,
                session_id=session_id or None,
                tags=tags or None,
                metadata={key: str(value) for key, value in trace_attributes.items()},
            ),
            trace_context(user_id=user_id, session_id=session_id, attributes=trace_attributes),
        ):
            yield root
    finally:
        otel_context.detach(token)


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[Span]:
    """A stage span under the current one; ``attributes`` as for ``Span.set``."""
    if _client is None:
        yield _NOOP
        return
    with _observe(name, attributes) as span:
        yield span
