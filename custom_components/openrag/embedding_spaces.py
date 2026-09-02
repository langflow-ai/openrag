"""Provider-aware embedding-space discovery shared by OpenRAG Langflow modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LEGACY_ROUTE_PREFIX = "legacy:"
INDEXED_ROUTE_PREFIX = "space:"


@dataclass(frozen=True)
class EmbeddingSpace:
    """One indexed vector space and the model route needed to query it."""

    space_id: str
    route_model: str
    field_identity: str
    legacy: bool = False


def build_embedding_space_aggregation(
    *,
    size: int,
    qualified_after: dict[str, Any] | None = None,
    legacy_after: dict[str, Any] | None = None,
    include_qualified: bool = True,
    include_legacy: bool = True,
) -> dict[str, Any]:
    """Build pageable discovery aggregations for exact and legacy vector spaces."""
    aggregations: dict[str, Any] = {}
    if include_qualified:
        composite: dict[str, Any] = {
            "size": size,
            "sources": [{"space_id": {"terms": {"field": "embedding_space_id"}}}],
        }
        if qualified_after:
            composite["after"] = qualified_after
        aggregations["embedding_spaces"] = {"composite": composite}

    if include_legacy:
        composite = {
            "size": size,
            "sources": [{"model": {"terms": {"field": "embedding_model"}}}],
        }
        if legacy_after:
            composite["after"] = legacy_after
        aggregations["legacy_embedding_models"] = {"composite": composite}
    return aggregations


def embedding_space_after_keys(
    result: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return composite pagination cursors for exact and legacy aggregations."""
    aggregations = result.get("aggregations", {})
    qualified_after = aggregations.get("embedding_spaces", {}).get("after_key")
    legacy_after = aggregations.get("legacy_embedding_models", {}).get("after_key")
    return qualified_after, legacy_after


def embedding_spaces_from_aggregation(result: dict[str, Any]) -> list[EmbeddingSpace]:
    """Convert an OpenSearch aggregation response into stable retrieval identities."""
    aggregations = result.get("aggregations", {})
    qualified_buckets = aggregations.get("embedding_spaces", {}).get("buckets", [])
    legacy_buckets = aggregations.get("legacy_embedding_models", {}).get("buckets", [])

    spaces: list[EmbeddingSpace] = []
    seen: set[str] = set()
    for bucket in qualified_buckets:
        key = bucket.get("key")
        space_id = str(key.get("space_id") if isinstance(key, dict) else key or "").strip()
        if not space_id or space_id in seen:
            continue
        seen.add(space_id)
        spaces.append(
            EmbeddingSpace(
                space_id=space_id,
                route_model=f"{INDEXED_ROUTE_PREFIX}{space_id}",
                field_identity=space_id,
            )
        )

    for bucket in legacy_buckets:
        key = bucket.get("key")
        model = str(key.get("model") if isinstance(key, dict) else key or "").strip()
        space_id = f"legacy:{model}"
        if not model or space_id in seen:
            continue
        seen.add(space_id)
        spaces.append(
            EmbeddingSpace(
                space_id=space_id,
                route_model=f"{LEGACY_ROUTE_PREFIX}{model}",
                field_identity=model,
                legacy=True,
            )
        )
    return spaces
