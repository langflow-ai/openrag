"""Feature-flag gating for the preview-mode ingest backend."""

from config.settings import is_ingest_preview_flag_enabled
from utils.run_mode_utils import is_run_mode_oss, is_run_mode_saas


def is_ingest_preview_enabled() -> bool:
    """Whether the preview-mode ingest backend is active.

    Gated behind an explicit opt-in feature flag so merging to main does not
    change behavior for existing installs. The flag defaults to ``false`` --
    set ``OPENRAG_INGEST_PREVIEW_ENABLED=true`` to turn it on. The run-mode
    check is AND-ed with the flag: preview is only ever available in OSS and
    SaaS run modes (never on_prem), and even there only when the flag is set.

    The raw env read lives in ``config.settings`` (the single place that owns
    ``os.environ`` parsing); this module only layers the run-mode gate on top.
    """
    if not is_ingest_preview_flag_enabled():
        return False
    return is_run_mode_oss() or is_run_mode_saas()
