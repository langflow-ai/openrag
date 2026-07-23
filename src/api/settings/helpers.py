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

from config.settings import clients, is_no_auth_mode
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Provider names in priority order. LLM supports anthropic; embeddings do not.
_LLM_PROVIDER_NAMES = ("openai", "anthropic", "watsonx", "ollama")
_EMBEDDING_PROVIDER_NAMES = ("openai", "watsonx", "ollama")


def _configured_provider_names(config, provider_names) -> list:
    """Return the provider names from `provider_names` marked configured in the OpenRAG config."""
    providers = config.providers
    return [name for name in provider_names if getattr(providers, name).configured]


def _first_configured_llm_provider(config, excluding: str) -> str:
    """Return the first configured LLM provider that isn't `excluding`."""
    for p in _LLM_PROVIDER_NAMES:
        if p != excluding and getattr(config.providers, p).configured:
            return p
    return "openai"


def _first_configured_embedding_provider(config, excluding: str) -> str:
    """Return the first configured embedding provider (openai/watsonx/ollama) that isn't `excluding`, or "" if none."""
    for p in _EMBEDDING_PROVIDER_NAMES:
        if p != excluding and getattr(config.providers, p).configured:
            return p
    return ""


def _default_llm_model(provider: str) -> str:
    """Return the default LLM model for a provider."""
    from config.model_constants import (
        ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
        OPENAI_DEFAULT_LANGUAGE_MODEL,
    )

    return {
        "openai": OPENAI_DEFAULT_LANGUAGE_MODEL,
        "anthropic": ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
        "watsonx": "ibm/granite-3-8b-instruct",
        "ollama": "llama3",
    }.get(provider, "")


def _default_embedding_model(provider: str) -> str:
    """Return the default embedding model for a provider."""
    from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL

    return {
        "openai": OPENAI_DEFAULT_EMBEDDING_MODEL,
        "watsonx": "ibm/granite-embedding-278m-multilingual",
        "ollama": "nomic-embed-text",
    }.get(provider, "")


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
