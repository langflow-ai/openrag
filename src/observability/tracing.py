"""Backend tracing to Langfuse.

Every model call the backend makes goes through LiteLLM in
``services/llm_gateway.py`` — including the embedding and chat calls Langflow
proxies to ``/v1/*`` — so tracing hooks in once, as LiteLLM's ``langfuse_otel``
callback, rather than at each call site. That callback builds its own private
OpenTelemetry provider exporting OTLP to ``$LANGFUSE_BASE_URL/api/public/otel`` and
does not replace the global provider, and it parents each call under whatever
OTel span is active, so ingest and search spans opened around gateway calls
nest them automatically.

Off by default (``OPENRAG_TRACING_ENABLED``). When off, nothing is registered
and neither LiteLLM nor the OTel SDK is imported here.

Content policy: traces carry metadata only (model, provider, latency, token
usage, cost, errors) unless content capture is opted into — and in SaaS run
mode that takes a second flag. Decision record:
``local/plans/backend-tracing-decision.md``.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

from config.settings import (
    get_langfuse_host,
    is_tracing_capture_content_flag_enabled,
    is_tracing_content_allowed_in_saas,
    is_tracing_flag_enabled,
    langfuse_keys_configured,
)
from utils.logging_config import get_logger
from utils.run_mode_utils import get_run_mode, is_run_mode_saas

logger = get_logger(__name__)

TRACING_CALLBACK = "langfuse_otel"

# LiteLLM setting, read from the environment per request (``get_secret_bool``).
_LITELLM_REQUEST_SPAN_ENV_VAR = "USE_OTEL_LITELLM_REQUEST_SPAN"
# OpenTelemetry SDK setting, read when a TracerProvider is constructed.
_OTEL_SAMPLER_ENV_VAR = "OTEL_TRACES_SAMPLER"

# Set by configure_tracing(); gates the per-call metadata below so a backend
# running untraced passes LiteLLM exactly what it did before tracing existed.
_enabled = False

# Who the work in progress is for (see trace_context): read by gateway calls
# and by the ingest/search traces in observability.spans.
_call_context: ContextVar[Mapping[str, Any]] = ContextVar(
    "openrag_trace_context", default=MappingProxyType({})
)


def content_capture_enabled() -> bool:
    """Whether traces may carry prompts, completions, chunk text, queries and filenames."""
    if not is_tracing_capture_content_flag_enabled():
        return False
    if is_run_mode_saas():
        return is_tracing_content_allowed_in_saas()
    return True


def configure_tracing() -> bool:
    """Register the Langfuse callback on LiteLLM when tracing is enabled.

    Returns True when tracing is active. Misconfiguration (missing keys, missing
    ``tracing`` extra) warns and leaves the backend running untraced rather than
    failing startup — the same stance as the Instana gate.
    """
    if not is_tracing_flag_enabled():
        return False

    if not langfuse_keys_configured():
        logger.warning(
            "OPENRAG_TRACING_ENABLED is set but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
            "are missing; backend tracing is disabled."
        )
        return False

    try:
        import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
        import opentelemetry.sdk.trace  # noqa: F401
    except ImportError:
        logger.warning(
            "OPENRAG_TRACING_ENABLED is set but the tracing dependencies are not "
            "installed; backend tracing is disabled. Install the optional extra with "
            "`uv sync --extra tracing`."
        )
        return False

    import litellm

    # Without this, a call made while another OTel span is active (an ingest or
    # search span, or Instana's HTTP span) gets no span of its own: LiteLLM
    # writes its attributes onto that caller span instead — usually already
    # ended by the time the async callback runs, or owned by another exporter —
    # so nothing reaches Langfuse. With it, every call is its own child span.
    os.environ.setdefault(_LITELLM_REQUEST_SPAN_ENV_VAR, "true")
    # LiteLLM builds its tracer providers with the SDK default sampler, which
    # follows the parent's sampling decision. Instana's HTTP spans are active
    # during every request and are never sampled, so with Instana on that would
    # silently drop every LLM span. Record unconditionally; the spans still join
    # the request's trace id. Read when each provider is built, i.e. after this.
    os.environ.setdefault(_OTEL_SAMPLER_ENV_VAR, "always_on")
    # LiteLLM reads its host only from LANGFUSE_OTEL_HOST / LANGFUSE_HOST, so
    # hand it the one our spans use too (LANGFUSE_OTEL_HOST, LiteLLM's own
    # override, still wins for LiteLLM).
    if not os.environ.get("LANGFUSE_OTEL_HOST"):
        os.environ["LANGFUSE_HOST"] = get_langfuse_host()

    capture = content_capture_enabled()
    # Read by LiteLLM on every request: forces its OTel logger to NO_CONTENT,
    # so prompts, completions and embedding inputs never leave the process.
    litellm.turn_off_message_logging = not capture
    if TRACING_CALLBACK not in litellm.callbacks:
        litellm.callbacks.append(TRACING_CALLBACK)

    from observability.spans import init_span_client

    init_span_client()

    global _enabled
    _enabled = True
    logger.info("Backend tracing enabled", backend="langfuse", capture_content=capture)
    return True


@contextmanager
def trace_context(
    *,
    source: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    purpose: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    """Describe the work inside this block to its traces: gateway calls and roots.

    ``source`` is who asked (``langflow`` or the default ``openrag``),
    ``user_id`` and ``session_id`` become Langfuse's user and session, and
    ``purpose`` overrides the call site's own (e.g. ``dimension_probe``).
    ``attributes`` are extra ``openrag.*`` trace metadata. Blocks nest: inner
    values win, and leaving a block restores the outer ones.
    """
    fields = dict(_call_context.get())
    for key, value in (
        ("source", source),
        ("user_id", user_id),
        ("session_id", session_id),
        ("purpose", purpose),
    ):
        if value is not None:
            fields[key] = value
    if attributes:
        fields["attributes"] = {**fields.get("attributes", {}), **attributes}
    token = _call_context.set(MappingProxyType(fields))
    try:
        yield
    finally:
        _call_context.reset(token)


def current_trace_context() -> Mapping[str, Any]:
    """The fields set by the enclosing ``trace_context`` blocks (read-only)."""
    return _call_context.get()


def gateway_trace_kwargs(
    kind: str, purpose: str, *, provider: str | None = None, **sizes: Any
) -> dict[str, Any]:
    """LiteLLM kwargs that label one gateway call in Langfuse; ``{}`` when untraced.

    ``kind`` is ``embedding`` or ``chat``; ``purpose`` is what the call is for
    (``ingest``, ``query``, ``completion``, ...) unless the call context
    overrides it. ``provider`` is OpenRAG's provider id, which can differ from
    LiteLLM's route (``watsonx_onprem``, custom providers). ``sizes`` are counts recorded as ``openrag.<kind>.<name>``;
    None values are left out. Never pass content here: this metadata is sent
    whatever the content-capture setting.

    LiteLLM's ``langfuse_otel`` maps ``generation_name`` to the observation
    name, ``trace_user_id`` / ``session_id`` to Langfuse's user and session,
    and ``trace_metadata`` keys to metadata; it drops other keys. LiteLLM
    consumes ``metadata`` itself and never sends it to the provider.
    """
    if not _enabled:
        return {}
    context = _call_context.get()
    purpose = context.get("purpose") or purpose
    source = context.get("source") or "openrag"
    trace_metadata: dict[str, Any] = {
        "openrag.source": source,
        "openrag.purpose": purpose,
        "openrag.run_mode": get_run_mode(),
        **context.get("attributes", {}),
    }
    if provider:
        trace_metadata["openrag.provider"] = provider
    trace_metadata.update(
        {f"openrag.{kind}.{name}": value for name, value in sizes.items() if value is not None}
    )
    metadata: dict[str, Any] = {
        "generation_name": f"{kind}.{purpose}",
        "tags": [f"source:{source}", f"purpose:{purpose}"],
        "trace_metadata": trace_metadata,
    }
    if context.get("user_id"):
        metadata["trace_user_id"] = context["user_id"]
    if context.get("session_id"):
        metadata["session_id"] = context["session_id"]
    return {"metadata": metadata}
