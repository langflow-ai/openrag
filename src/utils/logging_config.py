import os
import sys
from typing import Any, Dict
import structlog
from structlog import processors


def configure_logging(
    log_level: str = "INFO",
    json_logs: bool = False,
    include_timestamps: bool = True,
    service_name: str = "openrag"
) -> None:
    """Configure structlog for the application."""
    
    # Convert string log level to actual level
    level = getattr(structlog.stdlib.logging, log_level.upper(), structlog.stdlib.logging.INFO)
    
    # Base processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]
    
    if include_timestamps:
        shared_processors.append(structlog.processors.TimeStamper(fmt="iso"))
    
    # Add service name to all logs
    shared_processors.append(
        structlog.processors.CallsiteParameterAdder(
            parameters=[structlog.processors.CallsiteParameter.FUNC_NAME]
        )
    )
    
    # Console output configuration
    if json_logs or os.getenv("LOG_FORMAT", "").lower() == "json":
        # JSON output for production/containers
        shared_processors.append(structlog.processors.JSONRenderer())
        console_renderer = structlog.processors.JSONRenderer()
    else:
        # Pretty colored output for development
        console_renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
            exception_formatter=structlog.dev.plain_traceback,
        )
    
    # Configure structlog
    structlog.configure(
        processors=shared_processors + [console_renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )
    
    # Add global context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a configured logger instance."""
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()


# Convenience function to configure logging from environment
def configure_from_env() -> None:
    """Configure logging from environment variables."""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    json_logs = os.getenv("LOG_FORMAT", "").lower() == "json"
    service_name = os.getenv("SERVICE_NAME", "openrag")
    
    configure_logging(
        log_level=log_level,
        json_logs=json_logs,
        service_name=service_name
    )