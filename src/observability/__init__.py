"""Observability bootstrap helpers (APM tracers and friends).

Kept separate from `utils/` because the modules here run *before* the rest of
the application is importable — see `instana_boot` for why that matters.
"""
