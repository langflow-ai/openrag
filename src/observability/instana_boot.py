"""Instana APM gate.

This lives in its own module for one reason: the Instana tracer monkey-patches
``httpx``, ``urllib3``, ``sqlalchemy``, ``starlette``, ``fastapi``, and
``logging`` at *import* time, so it must be imported before any of them. That
rules out reading the flag from ``config/settings.py`` — importing that module
pulls in the very libraries the tracer has to patch first — which makes this
the documented exception to "config/settings.py is the only place that reads
``os.environ`` directly".

``bootstrap.load_env()`` calls :func:`boot_instana` immediately after loading
``.env`` and configuring structlog, which is the earliest point at which the
flag is readable and a warning can be logged.
"""

import os

INSTANA_ENABLED_ENV_VAR = "INSTANA_ENABLED"

# Same spelling the Kubernetes path accepts (`isTruthyEnvValue` in the
# operator's env.go), so a value that enables tracing there enables it here.
_TRUTHY_VALUES = frozenset({"true", "1", "yes"})


def is_instana_enabled(value: str | None = None) -> bool:
    """Return True when ``INSTANA_ENABLED`` asks for tracing.

    Reads the process environment when ``value`` is not supplied, which is what
    the boot path does; passing it explicitly keeps the parsing testable.
    """
    if value is None:
        value = os.environ.get(INSTANA_ENABLED_ENV_VAR, "")
    return value.strip().lower() in _TRUTHY_VALUES


def boot_instana() -> bool:
    """Load the Instana tracer when enabled. Returns True when it was loaded.

    Importing ``instana`` *is* the activation step — the package runs
    ``boot_agent()`` at import time. A missing package is not fatal: the tracer
    ships as the optional ``apm`` extra, so an install without it warns and
    runs untraced rather than failing to start.
    """
    if not is_instana_enabled():
        return False

    try:
        import instana  # noqa: F401  — the import is the activation
    except ImportError:
        from utils.logging_config import get_logger

        get_logger(__name__).warning(
            "INSTANA_ENABLED is set but the 'instana' package is not installed; "
            "APM tracing is disabled. Install the optional extra with "
            "`uv sync --extra apm`."
        )
        return False

    return True
