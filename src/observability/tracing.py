"""Backend tracing to Langfuse.

Every model call the backend makes goes through LiteLLM in
``services/llm_gateway.py`` — including the embedding and chat calls Langflow
proxies to ``/v1/*`` — so tracing hooks in once, as LiteLLM's ``langfuse_otel``
callback, rather than at each call site. That callback builds its own private
OpenTelemetry provider exporting OTLP to ``$LANGFUSE_HOST/api/public/otel`` and
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

from config.settings import (
    is_tracing_capture_content_flag_enabled,
    is_tracing_content_allowed_in_saas,
    is_tracing_flag_enabled,
    langfuse_keys_configured,
)
from utils.logging_config import get_logger
from utils.run_mode_utils import is_run_mode_saas

logger = get_logger(__name__)

TRACING_CALLBACK = "langfuse_otel"

# LiteLLM setting, read from the environment per request (``get_secret_bool``).
_LITELLM_REQUEST_SPAN_ENV_VAR = "USE_OTEL_LITELLM_REQUEST_SPAN"
# OpenTelemetry SDK setting, read when a TracerProvider is constructed.
_OTEL_SAMPLER_ENV_VAR = "OTEL_TRACES_SAMPLER"

# Langflow and the Langfuse SDK treat an empty LANGFUSE_HOST as Langfuse Cloud
# EU; LiteLLM's langfuse_otel treats it as Cloud US. Pin the backend to the same
# default so its traces land in the same project as Langflow's.
_LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"


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
    if not (os.environ.get("LANGFUSE_OTEL_HOST") or os.environ.get("LANGFUSE_HOST")):
        os.environ["LANGFUSE_HOST"] = _LANGFUSE_DEFAULT_HOST

    capture = content_capture_enabled()
    # Read by LiteLLM on every request: forces its OTel logger to NO_CONTENT,
    # so prompts, completions and embedding inputs never leave the process.
    litellm.turn_off_message_logging = not capture
    if TRACING_CALLBACK not in litellm.callbacks:
        litellm.callbacks.append(TRACING_CALLBACK)

    logger.info("Backend tracing enabled", backend="langfuse", capture_content=capture)
    return True
