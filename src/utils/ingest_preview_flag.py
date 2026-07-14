"""Feature-flag gating for the preview-mode ingest backend."""

import os

from utils.run_mode_utils import is_run_mode_oss, is_run_mode_saas


def is_ingest_preview_enabled() -> bool:
    """Whether the preview-mode ingest backend is active.

    Gated behind an explicit opt-in feature flag so merging to main does not
    change behavior for existing installs. The flag defaults to ``false`` --
    set ``OPENRAG_INGEST_PREVIEW_ENABLED=true`` to turn it on. The run-mode
    check is AND-ed with the flag: preview is only ever available in OSS and
    SaaS run modes (never on_prem), and even there only when the flag is set.
    """
    if not _ingest_preview_flag_enabled():
        return False
    return is_run_mode_oss() or is_run_mode_saas()


def _ingest_preview_flag_enabled() -> bool:
    raw = os.getenv("OPENRAG_INGEST_PREVIEW_ENABLED", "false").strip().lower()
    return raw in ("true", "1", "yes", "on")
