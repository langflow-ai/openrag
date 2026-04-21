import logging
import logging.config
import os
import re
import sys
from typing import Any, Dict

import structlog
from structlog import processors

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOC_WIDTH_SHORT = 30
LOC_WIDTH_LONG = 60

LEVEL_COLORS = {
    "DEBUG": "\033[36m",       # Cyan
    "INFO": "\033[32m",        # Green
    "WARNING": "\033[33m",     # Yellow
    "ERROR": "\033[31m",       # Red
    "CRITICAL": "\033[1;31m",  # Bold red
}
DIM = "\033[38;5;244m"   # Medium grey
RESET = "\033[0m"

_SENSITIVE_HEADER_RE = re.compile(
    r"(key|token|secret|password|apikey|credential|jwt|auth)", re.IGNORECASE
)

# Shared processors stored at module level so configure_stdlib_logging() can
# reference the same chain that configure_logging() assembled.
_shared_processors: list = []


# ---------------------------------------------------------------------------
# Standalone processors (module-level so they can be reused in stdlib bridge)
# ---------------------------------------------------------------------------

def drop_color_message_key(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Remove uvicorn's duplicate color_message field when bridging via stdlib."""
    event_dict.pop("color_message", None)
    return event_dict


def filter_health_and_metrics(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Drop only the access-log entry for high-frequency health/metrics endpoints.

    Errors and warnings on these paths still surface — only the routine
    [API] Request INFO line is suppressed to avoid log noise.
    """
    path = event_dict.get("path", "")
    if path not in ("/health", "/metrics", "/healthz", "/docs", "/openapi.json"):
        return event_dict
    event = event_dict.get("event", "")
    level = str(event_dict.get("level", "info")).lower()
    if event == "[API] Request" and level in ("debug", "info"):
        raise structlog.DropEvent()
    return event_dict


def suppress_third_party_noise(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Drop WARNING/INFO/DEBUG log lines that originate from installed packages.

    Third-party libraries (opensearch-py, httpx, boto3 …) log every HTTP
    request at WARNING level during normal operation.  These are pure noise in
    production — only ERROR and above from library code is actionable.
    """
    pathname = event_dict.get("pathname", "")
    level = event_dict.get("level", "info")
    if (
        (".venv" in pathname or "site-packages" in pathname)
        and level not in ("error", "critical")
    ):
        raise structlog.DropEvent()
    return event_dict


def clean_log_location(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Shorten pathname to a package-relative form for readability.

    Strips the leading venv/site-packages prefix so logs show
    ``opensearchpy/connection/base.py`` instead of the full absolute path.
    """
    pathname = event_dict.get("pathname", "")
    marker = "site-packages/"
    idx = pathname.find(marker)
    if idx != -1:
        event_dict["pathname"] = pathname[idx + len(marker):]
    return event_dict


def add_global_fields_factory(service: str, env: str, version: str):
    """Return a processor that stamps every event with service metadata."""
    def processor(_, __, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("env", env)
        event_dict.setdefault("version", version)
        return event_dict
    return processor


# ---------------------------------------------------------------------------
# Security helper
# ---------------------------------------------------------------------------

def sanitize_headers(headers: dict) -> dict:
    """Return a copy of *headers* with values of sensitive keys masked."""
    return {
        k: "***" if _SENSITIVE_HEADER_RE.search(k) else v
        for k, v in headers.items()
    }


# ---------------------------------------------------------------------------
# Main configuration
# ---------------------------------------------------------------------------

def configure_logging(
    log_level: str = "INFO",
    json_logs: bool = False,
    include_timestamps: bool = True,
    service_name: str = "openrag",
    app_env: str = "production",
    app_version: str = "unknown",
) -> None:
    """Configure structlog for the application."""
    global _shared_processors

    level = getattr(logging, log_level.upper(), logging.INFO)

    use_json = json_logs or os.getenv("LOG_FORMAT", "").lower() == "json"

    # Base processors — always run first
    base_processors = [
        structlog.contextvars.merge_contextvars,
        filter_health_and_metrics,
        suppress_third_party_noise,
        clean_log_location,
        add_global_fields_factory(service_name, app_env, app_version),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        drop_color_message_key,
    ]

    if include_timestamps:
        base_processors.append(
            structlog.processors.TimeStamper(fmt="iso", utc=True)
        )

    base_processors.append(
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.PATHNAME,
            ]
        )
    )

    _shared_processors = list(base_processors)

    if use_json:
        # Production: structured tracebacks (queryable in ELK/Datadog/Splunk)
        render_processors = [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: human-readable with exception info as text
        use_colors = (
            "NO_COLOR" not in os.environ
            and hasattr(sys.stderr, "isatty")
            and sys.stderr.isatty()
        )

        def custom_formatter(logger, log_method, event_dict):
            timestamp = event_dict.pop("timestamp", "")
            pathname = event_dict.pop("pathname", "")
            filename = event_dict.pop("filename", "")
            lineno = event_dict.pop("lineno", "")
            lvl = event_dict.pop("level", "").upper()

            if filename and lineno:
                location = f"{filename}:{lineno}"
                loc_width = LOC_WIDTH_SHORT
            elif pathname and lineno:
                location = f"{pathname}:{lineno}"
                loc_width = LOC_WIDTH_LONG
            elif filename:
                location = filename
                loc_width = LOC_WIDTH_SHORT
            elif pathname:
                location = pathname
                loc_width = LOC_WIDTH_LONG
            else:
                location = "unknown"
                loc_width = LOC_WIDTH_SHORT

            message_parts = []
            event = event_dict.pop("event", "")
            if event:
                message_parts.append(event)

            if use_colors:
                colored_timestamp = f"{DIM}{timestamp}{RESET}"
                color = LEVEL_COLORS.get(lvl, "")
                colored_level = f"{color}{lvl:<7}{RESET}"
            else:
                colored_timestamp = timestamp
                colored_level = f"{lvl:<7}"

            header = f"[{colored_timestamp}] [{colored_level}] [{location:<{loc_width}}] "
            visible_header = f"[{timestamp}] [{lvl:<7}] [{location:<{loc_width}}] "

            extra = {
                k: v
                for k, v in event_dict.items()
                if k not in ("service", "env", "version", "func_name")
            }
            if extra:
                padding = " " * len(visible_header)
                for key, value in extra.items():
                    message_parts.append(f"\n{padding}- {key}: {value}")

            return f"{header}{''.join(message_parts)}"

        render_processors = [
            structlog.dev.set_exc_info,
            structlog.processors.format_exc_info,
            custom_formatter,
        ]

    structlog.configure(
        processors=base_processors + render_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def configure_stdlib_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    """Bridge Python stdlib logging (uvicorn, httpx, etc.) through structlog.

    Must be called after configure_logging() so _shared_processors is populated.

    Key behaviours:
    - Uses the same renderer (JSON vs console) as the main structlog config.
    - Takes over uvicorn's loggers so its raw "INFO:     Started server…" lines
      disappear and are replaced by our structured request logs from the ASGI middleware.
    - Captures Python warnings (warnings.warn) through logging.
    - Suppresses noisy third-party libs at ERROR+ only.
    """
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(sort_keys=False)
    )

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "structlog": {
                "class": "logging.StreamHandler",
                "formatter": "structlog",
                "stream": "ext://sys.stderr",
            }
        },
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    drop_color_message_key,
                    structlog.processors.dict_tracebacks if json_logs else structlog.processors.format_exc_info,
                    renderer,
                ],
                "foreign_pre_chain": list(_shared_processors),
            }
        },
        "root": {"handlers": ["structlog"], "level": log_level},
        "loggers": {
            # Uvicorn — override its self-configured handlers so our formatter
            # is used instead of uvicorn's default "INFO:     …" format.
            # uvicorn.access is entirely replaced by RequestLoggingMiddleware.
            "uvicorn":         {"handlers": ["structlog"], "level": "INFO",     "propagate": False},
            "uvicorn.error":   {"handlers": ["structlog"], "level": "WARNING",  "propagate": False},
            "uvicorn.access":  {"handlers": ["structlog"], "level": "CRITICAL", "propagate": False},
            # Third-party libs: ERROR+ only — suppress HTTP-request-level noise.
            "httpcore":        {"level": "ERROR", "propagate": True},
            "httpx":           {"level": "ERROR", "propagate": True},
            "urllib3":         {"level": "ERROR", "propagate": True},
            # openai SDK logs full request payloads (URL, headers, body) at DEBUG.
            # Headers include forwarded X-LANGFLOW-GLOBAL-VAR-* JWTs/API keys — suppress below WARNING.
            "openai":          {"level": "WARNING", "propagate": True},
            "boto3":           {"level": "ERROR", "propagate": True},
            "botocore":        {"level": "ERROR", "propagate": True},
            # opensearch-py logs every HTTP request (incl. 401 health checks) at WARNING.
            # ERROR-only keeps the pipeline clean; true failures still surface.
            "opensearch":         {"level": "ERROR", "propagate": True},
            "opensearchpy":       {"level": "ERROR", "propagate": True},
            "opensearchpy.trace": {"level": "CRITICAL", "propagate": False},
            "elastic_transport":  {"level": "ERROR",    "propagate": True},
            # Suppress mcp/fastmcp library chatter
            "mcp":             {"level": "WARNING", "propagate": True},
            # Python warnings.warn() from libraries — these are startup noise
            # (duplicate operation IDs, insecure SSL, deprecations) that are not
            # actionable. Our code uses logger.warning() directly, not warnings.warn().
            "py.warnings":     {"level": "CRITICAL", "propagate": False},
        },
    })

    # Route Python warnings.warn() through the logging system (suppressed above for libs)
    logging.captureWarnings(True)


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a configured logger instance."""
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()


def configure_from_env() -> None:
    """Configure logging from environment variables."""
    from utils.version_utils import OPENRAG_VERSION  # avoid circular import at module level

    log_level = os.getenv("LOG_LEVEL", "INFO")
    json_logs = os.getenv("LOG_FORMAT", "").lower() == "json"
    service_name = os.getenv("SERVICE_NAME", "openrag")
    app_env = os.getenv("APP_ENV", "production")

    configure_logging(
        log_level=log_level,
        json_logs=json_logs,
        service_name=service_name,
        app_env=app_env,
        app_version=OPENRAG_VERSION,
    )
    configure_stdlib_logging(log_level=log_level, json_logs=json_logs)
