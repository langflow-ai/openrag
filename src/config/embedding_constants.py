"""Embedding model constants."""

import os

OPENAI_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_MODEL_PREFIX = "text-embedding"


def get_declared_default_embedding_model(provider: str) -> str:
    """Return the deployment-declared default embedding model for `provider`.

    Sourced directly from the EMBEDDING_MODEL / EMBEDDING_PROVIDER env vars
    the deployment is expected to set (Helm values / operator ConfigMap) to
    describe what this specific environment's embedding backend actually
    serves. Read directly rather than through ConfigManager's env-override
    path, which is skipped once the config has been manually edited — a
    protection against clobbering a user's own choices that shouldn't also
    block resolving a fallback when the user hasn't made one.

    Returns "" when the deployment hasn't declared a default for this
    provider. Callers MUST NOT substitute a hardcoded guess in that case —
    "openai" (and any other provider name) can mean anything from the real
    public API to an internal gateway with a curated model subset, so no
    single hardcoded model name is safe across deployments. A hardcoded
    guess here previously selected "text-embedding-3-small" in an
    environment whose gateway only served "text-embedding-3-large",
    silently failing every ingestion.
    """
    declared_provider = os.environ.get("EMBEDDING_PROVIDER", "")
    declared_model = os.environ.get("EMBEDDING_MODEL", "")
    if declared_provider == provider and declared_model:
        return declared_model
    return ""
