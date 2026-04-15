"""Utilities for determining the OpenRAG application run mode."""
import os

RUN_MODE_OSS: str = "oss"
RUN_MODE_SAAS: str = "saas"
RUN_MODE_ON_PREM: str = "on_prem"

_VALID_RUN_MODES = {RUN_MODE_OSS, RUN_MODE_SAAS, RUN_MODE_ON_PREM}
_DEFAULT_RUN_MODE = RUN_MODE_OSS


def is_run_mode_oss() -> bool:
    """Return True if the current run mode is "oss"."""
    return get_run_mode() == RUN_MODE_OSS


def is_run_mode_saas() -> bool:
    """Return True if the current run mode is "saas"."""
    return get_run_mode() == RUN_MODE_SAAS


def is_run_mode_on_prem() -> bool:
    """Return True if the current run mode is "on_prem"."""
    return get_run_mode() == RUN_MODE_ON_PREM


def get_run_mode() -> str:
    """Return the current OpenRAG run mode.

    Reads the OPENRAG_RUN_MODE environment variable. If unset or empty,
    defaults to "oss". If an unrecognized value is provided, defaults to "oss".
    """
    value = os.getenv("OPENRAG_RUN_MODE", "").strip().lower()
    if value in _VALID_RUN_MODES:
        return value
    return _DEFAULT_RUN_MODE
