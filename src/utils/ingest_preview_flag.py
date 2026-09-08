"""Feature-flag gating for the preview-mode ingest backend."""

from config.settings import is_ingest_preview_flag_enabled
from utils.run_mode_utils import RUN_MODE_OSS, get_run_mode

# Run modes eligible once OPENRAG_INGEST_PREVIEW_ENABLED is on.
# SaaS omitted until product approval — re-add RUN_MODE_SAAS here to restore.
_INGEST_PREVIEW_RUN_MODES = frozenset({RUN_MODE_OSS})


def is_ingest_preview_enabled() -> bool:
    """Whether the preview-mode ingest backend is active.

    Gated behind an explicit opt-in feature flag so merging to main does not
    change behavior for existing installs. The flag defaults to ``false`` --
    set ``OPENRAG_INGEST_PREVIEW_ENABLED=true`` to turn it on. The run-mode
    check is AND-ed with the flag: preview is only available for modes in
    ``_INGEST_PREVIEW_RUN_MODES`` (currently OSS only; SaaS deferred pending
    product approval), and even there only when the flag is set.

    The raw env read lives in ``config.settings`` (the single place that owns
    ``os.environ`` parsing); this module only layers the run-mode gate on top.
    """
    if not is_ingest_preview_flag_enabled():
        return False
    return get_run_mode() in _INGEST_PREVIEW_RUN_MODES
