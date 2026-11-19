"""Feature-flag gating for the date range v2 experience."""

from config.settings import is_date_range_v2_flag_enabled
from utils.run_mode_utils import RUN_MODE_OSS, get_run_mode

# Mirrors the frontend ``isDateRangeFilterEnabled`` run-mode gate (OSS only).
_DATE_RANGE_V2_RUN_MODES = frozenset({RUN_MODE_OSS})


def is_date_range_v2_enabled() -> bool:
    """Whether date range v2 is active.

    The ``OPENRAG_DATE_RANGE_V2_ENABLED`` flag (default ``false``) is AND-ed
    with the run mode: only modes in ``_DATE_RANGE_V2_RUN_MODES`` are eligible.
    """
    if not is_date_range_v2_flag_enabled():
        return False
    return get_run_mode() in _DATE_RANGE_V2_RUN_MODES
