"""Assess whether removing a model provider would degrade semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from config.settings import get_index_name
from services.model_catalog import catalog_owners
from utils.embedding_fields import (
    build_embedding_space_aggregation,
    embedding_space_after_keys,
    split_embedding_space_id,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

EMBEDDING_SPACE_PAGE_SIZE = 50


class ProviderRemovalStatus(StrEnum):
    """Result of checking indexed embedding provenance."""

    CLEAR = "clear"
    IN_USE = "in_use"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderRemovalOutcome:
    """Provider-removal impact without HTTP-specific policy."""

    status: ProviderRemovalStatus
    affected_models: tuple[dict[str, Any], ...] = ()
    unresolved_legacy_models: tuple[str, ...] = ()


class ProviderRemovalService:
    """Find every indexed embedding space that depends on one provider.

    Provider-qualified ``embedding_space_id`` values are authoritative. Legacy
    documents contain only ``embedding_model``; those are accepted only when an
    operator mapping or the model catalogue identifies exactly one owner.
    """

    def __init__(self, opensearch_client):
        """Use the deployment-wide OpenSearch client for corpus inspection."""
        self._opensearch = opensearch_client

    async def assess(self, provider: str, config) -> ProviderRemovalOutcome:
        """Return confirmed usage, confirmed absence, or an unknown result."""
        provider_key = (provider or "").strip().lower()
        if provider_key == "anthropic":
            return ProviderRemovalOutcome(ProviderRemovalStatus.CLEAR)

        try:
            affected = await self._qualified_models(provider_key)
            legacy_models = await self._legacy_models()
            unresolved: list[str] = []
            legacy_mapping = getattr(
                config.knowledge,
                "legacy_embedding_provider_map",
                {},
            )
            if not isinstance(legacy_mapping, dict):
                legacy_mapping = {}

            for model, doc_count in legacy_models:
                mapped_provider = str(legacy_mapping.get(model) or "").strip().lower()
                if not mapped_provider:
                    owners = catalog_owners(model)
                    mapped_provider = owners[0] if len(owners) == 1 else ""
                if not mapped_provider:
                    unresolved.append(model)
                elif mapped_provider == provider_key:
                    affected[model] = affected.get(model, 0) + doc_count

            payload = tuple(
                {"model": model, "doc_count": doc_count} for model, doc_count in affected.items()
            )
            if unresolved:
                return ProviderRemovalOutcome(
                    ProviderRemovalStatus.UNKNOWN,
                    affected_models=payload,
                    unresolved_legacy_models=tuple(unresolved),
                )
            return ProviderRemovalOutcome(
                ProviderRemovalStatus.IN_USE if payload else ProviderRemovalStatus.CLEAR,
                affected_models=payload,
            )
        except Exception as exc:
            logger.warning(
                "Could not determine embedding usage before provider removal",
                provider=provider_key,
                error=str(exc),
            )
            return ProviderRemovalOutcome(ProviderRemovalStatus.UNKNOWN)

    async def _qualified_models(self, provider: str) -> dict[str, int]:
        """Page provider-qualified spaces and combine their chunk counts."""
        affected: dict[str, int] = {}
        after = None
        while True:
            result = await self._opensearch.search(
                index=get_index_name(),
                body={
                    "size": 0,
                    "query": {
                        "prefix": {"embedding_space_id": f"{provider}:"},
                    },
                    "aggs": build_embedding_space_aggregation(
                        size=EMBEDDING_SPACE_PAGE_SIZE,
                        qualified_after=after,
                        include_legacy=False,
                    ),
                },
                params={"terminate_after": 0},
            )
            buckets = result.get("aggregations", {}).get("embedding_spaces", {}).get("buckets", [])
            for bucket in buckets:
                key = bucket.get("key")
                space_id = key.get("space_id") if isinstance(key, dict) else key
                space_provider, model = split_embedding_space_id(str(space_id or ""))
                if space_provider == provider and model:
                    affected[model] = affected.get(model, 0) + int(bucket.get("doc_count", 0))

            next_after, _ = embedding_space_after_keys(result)
            if not next_after or next_after == after:
                break
            after = next_after
        return affected

    async def _legacy_models(self) -> list[tuple[str, int]]:
        """Page model-only spaces written before provider provenance existed."""
        models: list[tuple[str, int]] = []
        after = None
        while True:
            result = await self._opensearch.search(
                index=get_index_name(),
                body={
                    "size": 0,
                    "query": {
                        "bool": {
                            "must_not": [
                                {"exists": {"field": "embedding_space_id"}},
                            ]
                        }
                    },
                    "aggs": build_embedding_space_aggregation(
                        size=EMBEDDING_SPACE_PAGE_SIZE,
                        legacy_after=after,
                        include_qualified=False,
                    ),
                },
                params={"terminate_after": 0},
            )
            buckets = (
                result.get("aggregations", {}).get("legacy_embedding_models", {}).get("buckets", [])
            )
            for bucket in buckets:
                key = bucket.get("key")
                model = key.get("model") if isinstance(key, dict) else key
                model_name = str(model or "").strip()
                if model_name:
                    models.append((model_name, int(bucket.get("doc_count", 0))))

            _, next_after = embedding_space_after_keys(result)
            if not next_after or next_after == after:
                break
            after = next_after
        return models
