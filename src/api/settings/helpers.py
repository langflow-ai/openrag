"""General helpers for the settings/onboarding endpoints.

Provider-fallback selection, embedding-model conflict detection (used to
warn before removing a provider whose embeddings are still indexed), the
BomaRAG-docs knowledge-filter creator, and a flows-service factory.

Lifted verbatim from the original `src/api/settings.py` (lines 371–480 and
1388–1455). No behavior change.
"""

from datetime import UTC
from typing import Any

from fastapi.responses import JSONResponse

from config.settings import clients, is_no_auth_mode
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Provider names in priority order. LLM supports anthropic; embeddings do not.
_LLM_PROVIDER_NAMES = ("openai", "anthropic", "watsonx", "ollama")
_EMBEDDING_PROVIDER_NAMES = ("openai", "watsonx", "ollama")


def _configured_provider_names(config, provider_names) -> list:
    """Return the provider names from `provider_names` marked configured in the BomaRAG config."""
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
    """Return the first configured LLM provider that isn't `excluding`."""
    for p in _LLM_PROVIDER_NAMES:
        if p != excluding and getattr(config.providers, p).configured:
            return p
    for provider, value in config.providers.custom.items():
        if provider != excluding and value.configured:
            return provider
    return "openai"


def _first_configured_embedding_provider(config, excluding: str) -> str:
    """Return the first configured embedding provider that isn't `excluding`, or "" if none."""
    for p in _EMBEDDING_PROVIDER_NAMES:
        if p != excluding and getattr(config.providers, p).configured:
            return p
    from services.model_catalog import catalog

    entries = {entry["key"]: entry for entry in catalog()["providers"]}
    for provider, value in config.providers.custom.items():
        if provider != excluding and value.configured:
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

    Instead, defer to whatever the deployment itself declared via
    EMBEDDING_MODEL/EMBEDDING_PROVIDER (see
    ``get_declared_default_embedding_model``). If the deployment hasn't
    declared a default for this provider, return "" and force the admin
    to pick a model the settings UI confirms is actually available.
    """
    from config.embedding_constants import get_declared_default_embedding_model

    return get_declared_default_embedding_model(provider)


async def _affected_embedding_models(
    provider: str,
    session_manager,
    user,
    models_service,
) -> list[dict[str, Any]]:
    """Find embedding models present in the corpus that belong to ``provider``.

    Used to warn users before they remove a provider whose embedding models
    were used to index documents — otherwise semantic search silently breaks
    for those docs. Returns a list of ``{"model": str, "doc_count": int}``.

    Conservative on errors (returns empty list) so infra issues don't block
    provider removal.
    """
    from config.settings import get_index_name
    from services.models_service import ModelsService

    provider_lower = provider.lower()
    if provider_lower == "anthropic":
        # Anthropic doesn't serve embedding models — nothing to warn about.
        return []

    try:
        # Refresh so the registry reflects currently-configured providers
        # before we use it to attribute models.
        await models_service.update_model_registry()
        registry = ModelsService._model_provider_registry

        # Use the admin client so DLS does not scope the aggregation to the
        # requesting user's documents. Provider removal is a global operation
        # that affects all tenants, so we must see every document's embedding
        # model regardless of ownership.
        agg_result = await clients.opensearch.search(
            index=get_index_name(),
            body={
                "size": 0,
                "aggs": {"embedding_models": {"terms": {"field": "embedding_model", "size": 50}}},
            },
            params={"terminate_after": 0},
        )
        buckets = agg_result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])

        affected: list[dict[str, Any]] = []
        for bucket in buckets:
            model = bucket.get("key")
            if not model:
                continue
            mapped = registry.get(model)
            # Narrow fallback: the watsonx registry bootstrap requires the
            # provider still be configured, so models from an about-to-be-
            # removed watsonx can still be attributed via the "ibm/" prefix.
            if mapped is None and provider_lower == "watsonx" and model.startswith("ibm/"):
                mapped = "watsonx"
            if mapped == provider_lower:
                affected.append({"model": model, "doc_count": bucket.get("doc_count", 0)})
        return affected
    except Exception as e:
        logger.warning(
            "Could not determine affected embedding models for provider removal",
            provider=provider,
            error=str(e),
        )
        return []


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


async def _create_bomarag_docs_filter(knowledge_filter_service, session_manager, user):
    """Create the BomaRAG Docs knowledge filter for onboarding"""
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
                # Filter by connector type to target BomaRAG docs only.
                "data_sources": ["*"],
                "document_types": ["*"],
                "owners": ["*"],
                "connector_types": ["bomarag_docs"],
            },
            "limit": 10,
            "scoreThreshold": 0,
            "color": "blue",
            "icon": "book",
        }
    )

    filter_doc = {
        "id": filter_id,
        "name": "BomaRAG Docs",
        "description": "Filter for BomaRAG documentation",
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
        logger.error("Failed to create BomaRAG Docs filter", error=result.get("error"))
        return None


def _get_flows_service():
    """Helper function to get flows service instance"""
    from services.flows_service import FlowsService

    return FlowsService()
