"""General helpers for the settings/onboarding endpoints.

Provider-fallback selection, embedding-model conflict detection (used to
warn before removing a provider whose embeddings are still indexed), the
OpenRAG-docs knowledge-filter creator, and a flows-service factory.

Lifted verbatim from the original `src/api/settings.py` (lines 371–480 and
1388–1455). No behavior change.
"""

from datetime import UTC
from typing import Any

from fastapi.responses import JSONResponse

from config.settings import is_no_auth_mode
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Provider names in priority order. LLM supports anthropic; embeddings do not.
_LLM_PROVIDER_NAMES = ("openai", "anthropic", "watsonx", "ollama")
_EMBEDDING_PROVIDER_NAMES = ("openai", "watsonx", "ollama")


def _configured_provider_names(config, provider_names) -> list:
    """Return the provider names from `provider_names` marked configured in the OpenRAG config."""
    providers = config.providers
    configured = [name for name in provider_names if getattr(providers, name).configured]
    from services.model_catalog import catalog

    entries = {entry["key"]: entry for entry in catalog()["providers"]}
    embedding = tuple(provider_names) == _EMBEDDING_PROVIDER_NAMES
    for provider, value in providers.custom.items():
        entry = entries.get(provider)
        supports_kind = bool(
            entry and (entry["embedding_models"] if embedding else entry["models"])
        )
        if value.configured and supports_kind and provider not in configured:
            configured.append(provider)
    return configured


def _first_configured_llm_provider(config, excluding: str) -> str:
    """Return the first configured LLM provider that isn't `excluding`.

    Only providers this run mode shows are eligible: falling back to one the
    config file hides would leave Settings pointing at a provider whose card
    the user cannot see (see ``config/model_providers.yaml``).
    """
    from config.model_providers import visible_provider_keys

    visible = visible_provider_keys()
    for p in _LLM_PROVIDER_NAMES:
        if p != excluding and p in visible and getattr(config.providers, p).configured:
            return p
    for provider, value in config.providers.custom.items():
        if provider != excluding and provider in visible and value.configured:
            return provider
    return "openai"


def _first_configured_embedding_provider(config, excluding: str) -> str:
    """Return the first configured embedding provider that isn't `excluding`, or "" if none.

    Providers hidden in this run mode are skipped, as in
    ``_first_configured_llm_provider``.
    """
    from config.model_providers import visible_provider_keys

    visible = visible_provider_keys()
    for p in _EMBEDDING_PROVIDER_NAMES:
        if p != excluding and p in visible and getattr(config.providers, p).configured:
            return p
    from services.model_catalog import catalog

    entries = {entry["key"]: entry for entry in catalog()["providers"]}
    for provider, value in config.providers.custom.items():
        if provider != excluding and provider in visible and value.configured:
            entry = entries.get(provider)
            if entry and entry["embedding_models"]:
                return provider
    return ""


def _default_llm_model(provider: str) -> str:
    """Return the static preferred LLM model for a provider.

    OpenAI/Anthropic have stable preferred defaults. Ollama/watsonx model IDs are
    dynamic from the live provider list — return empty so the frontend picks from
    the live list (default flag or first available).
    """
    from config.model_constants import (
        ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
        OPENAI_DEFAULT_LANGUAGE_MODEL,
    )

    return {
        "openai": OPENAI_DEFAULT_LANGUAGE_MODEL,
        "anthropic": ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
        "watsonx": "",
        "ollama": "",
    }.get(provider, "")


def _default_embedding_model(provider: str) -> str:
    """Return a fallback embedding model for `provider` on provider-removal
    reshuffle, or "" if none can be assumed safe.

    No provider gets a hardcoded model name here. A provider name like
    "openai" or "watsonx" doesn't reliably tell you which models are
    actually deployed — it's frequently an internal OpenAI/watsonx-
    compatible gateway with a curated, deployment-specific model subset.
    A hardcoded guess can silently select a model the gateway doesn't
    serve, breaking every ingestion with no clear signal why (see
    incident: hardcoded "text-embedding-3-small" was selected in an
    environment whose gateway only served "text-embedding-3-large").

    Azure is the exception: its model IDs are customer-defined deployment
    names, so removal always leaves the model empty for an explicit user
    choice. For other providers, defer to whatever the deployment declared via
    EMBEDDING_MODEL/EMBEDDING_PROVIDER (see
    ``get_declared_default_embedding_model``). If the deployment hasn't
    declared a default for the provider, return "" and force the admin
    to pick a model the settings UI confirms is actually available.
    """
    # Azure model identifiers are customer-defined deployment names. Even an
    # operator-declared default may belong to a different workspace/resource,
    # so provider removal must leave the choice open for the user.
    if provider == "azure":
        return ""

    from config.embedding_constants import get_declared_default_embedding_model

    return get_declared_default_embedding_model(provider)


def _embedding_conflict_response(
    provider_label: str, provider_key: str, affected: list[dict[str, Any]]
) -> JSONResponse:
    """Shared 409 response when removing a provider whose embedding models are
    still referenced by indexed documents."""
    model_names = [a["model"] for a in affected]
    return JSONResponse(
        {
            "error": (
                f"Removing {provider_label} will disable semantic search on "
                f"documents indexed with: {', '.join(model_names)}. "
                f"Re-ingest affected documents with another embedding model, "
                f"or retry with force_remove=true to proceed anyway."
            ),
            "code": "embedding_provider_in_use",
            "affected_provider": provider_key,
            "affected_models": affected,
        },
        status_code=409,
    )


def _embedding_usage_unknown_response(
    provider_label: str,
    provider_key: str,
    unresolved_legacy_models: tuple[str, ...],
) -> JSONResponse:
    """503 response when indexed embedding provenance cannot be verified."""
    payload: dict[str, Any] = {
        "error": (
            f"Could not verify whether indexed documents depend on {provider_label}. "
            "Retry when OpenSearch is available, configure legacy embedding provenance, "
            "or retry with force_remove=true to proceed anyway."
        ),
        "code": "embedding_usage_unknown",
        "affected_provider": provider_key,
    }
    if unresolved_legacy_models:
        payload["unresolved_legacy_models"] = list(unresolved_legacy_models)
    return JSONResponse(payload, status_code=503)


async def _create_openrag_docs_filter(knowledge_filter_service, session_manager, user):
    """Create the OpenRAG Docs knowledge filter for onboarding"""
    import json
    import uuid
    from datetime import datetime

    if not knowledge_filter_service:
        logger.error("Knowledge filter service not available")
        return None

    # Get JWT token
    jwt_token = user.jwt_token

    # In no-auth mode, set owner to None so filter is visible to all users
    # In auth mode, use the actual user as owner
    if is_no_auth_mode():
        owner_user_id = None
    else:
        owner_user_id = user.user_id

    # Create the filter document
    filter_id = str(uuid.uuid4())
    query_data = json.dumps(
        {
            "query": "",
            "filters": {
                # URL-based docs ingestion produces many source URLs.
                # Filter by connector type to target OpenRAG docs only.
                "data_sources": ["*"],
                "document_types": ["*"],
                "owners": ["*"],
                "connector_types": ["openrag_docs"],
            },
            "limit": 10,
            "scoreThreshold": 0,
            "color": "blue",
            "icon": "book",
        }
    )

    filter_doc = {
        "id": filter_id,
        "name": "OpenRAG Docs",
        "description": "Filter for OpenRAG documentation",
        "query_data": query_data,
        "owner": owner_user_id,
        "allowed_users": [],
        "allowed_groups": [],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    result = await knowledge_filter_service.create_knowledge_filter(
        filter_doc, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return filter_id
    else:
        logger.error("Failed to create OpenRAG Docs filter", error=result.get("error"))
        return None


def _get_flows_service():
    """Helper function to get flows service instance"""
    from services.flows_service import FlowsService

    return FlowsService()
