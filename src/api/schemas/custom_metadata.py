"""Public request models for typed custom metadata filters."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MetadataFilterCondition(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    operator: Literal[
        "equals",
        "not_equals",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "exists",
        "not_exists",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
    ]
    value: Any | None = None


class MetadataFilterGroup(BaseModel):
    op: Literal["and", "or"] = "and"
    conditions: list[MetadataFilterCondition | MetadataFilterGroup] = Field(
        min_length=1,
        max_length=50,
    )


class SearchFiltersRequest(BaseModel):
    data_sources: list[str] | None = None
    document_types: list[str] | None = None
    owners: list[str] | None = None
    connector_types: list[str] | None = None
    metadata: MetadataFilterGroup | None = None

    model_config = {"extra": "forbid"}


def dump_search_filters(filters: SearchFiltersRequest | dict[str, Any] | None):
    if isinstance(filters, SearchFiltersRequest):
        return filters.model_dump(exclude_none=True)
    return filters
