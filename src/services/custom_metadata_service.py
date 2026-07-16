"""Validation, indexing, discovery, and query compilation for custom metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

MetadataType = Literal["string", "number", "date", "boolean"]


@dataclass(frozen=True)
class NormalizedMetadata:
    source: dict[str, dict[str, Any]]
    index_entries: list[dict[str, Any]]


class CustomMetadataService:
    """Present one small metadata interface to ingest and retrieval callers."""

    VALUE_FIELDS: dict[str, str] = {
        "string": "string_value",
        "number": "number_value",
        "date": "date_value",
        "boolean": "boolean_value",
    }
    PROTECTED_KEYS = frozenset(
        {
            "allowed_groups",
            "allowed_principal_labels",
            "allowed_principals",
            "allowed_users",
            "chunk_embedding",
            "chunk_overlap",
            "chunk_size",
            "connector_file_id",
            "connector_type",
            "connector_types",
            "custom_metadata",
            "created_time",
            "data_sources",
            "document_id",
            "document_types",
            "embedding_dimensions",
            "embedding_model",
            "file_size",
            "filename",
            "indexed_time",
            "ingest_run_id",
            "is_sample_data",
            "metadata",
            "metadata_entries",
            "mimetype",
            "modified_time",
            "owner",
            "owner_email",
            "owner_name",
            "owners",
            "page",
            "parser",
            "source_url",
            "text",
            "user_permissions",
            "group_permissions",
        }
    )
    KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    def _session_factory(self):
        if self.session_factory is not None:
            return self.session_factory
        from db.engine import SessionLocal, init_engine

        if SessionLocal is None:
            init_engine()
            from db.engine import SessionLocal as initialized_session_factory

            return initialized_session_factory
        return SessionLocal

    async def register_entries(self, entries: list[dict[str, Any]] | None) -> None:
        normalized = self.normalize_entries(entries)
        if not normalized.source:
            return
        session_factory = self._session_factory()
        if session_factory is None:
            raise RuntimeError("Metadata field registry database is unavailable")
        from db.repositories.metadata_field_repo import MetadataFieldRepo

        async with session_factory() as session:
            repo = MetadataFieldRepo(session)
            for key, item in normalized.source.items():
                existing = await repo.get(key)
                metadata_type = item["type"]
                if existing is None:
                    await repo.add(key, metadata_type)
                elif existing.metadata_type != metadata_type:
                    raise ValueError(
                        f"Custom metadata '{key}' expected {existing.metadata_type}, "
                        f"received {metadata_type}"
                    )
            await session.commit()

    async def get_field_types(self) -> dict[str, str]:
        session_factory = self._session_factory()
        if session_factory is None:
            return {}
        from db.repositories.metadata_field_repo import MetadataFieldRepo

        async with session_factory() as session:
            rows = await MetadataFieldRepo(session).list_all()
            return {row.key: row.metadata_type for row in rows}

    async def build_filter_clauses(self, filters: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Compile built-in and custom public filters through one interface."""
        field_mapping = {
            "data_sources": "filename",
            "document_types": "mimetype",
            "owners": "owner",
            "connector_types": "connector_type",
        }
        clauses: list[dict[str, Any]] = []
        for key, value in (filters or {}).items():
            if key == "metadata":
                clauses.append(self.compile_expression(value, await self.get_field_types()))
                continue
            field = field_mapping.get(key)
            if field is None:
                raise ValueError(f"Unknown filter field '{key}'")
            if not isinstance(value, list):
                raise ValueError(f"Filter '{key}' must be a list")
            if "*" in value:
                continue
            if not value:
                clauses.append({"term": {field: "__IMPOSSIBLE_VALUE__"}})
            elif len(value) == 1:
                clauses.append({"term": {field: value[0]}})
            else:
                clauses.append({"terms": {field: value}})
        return clauses

    def normalize_entries(self, entries: list[dict[str, Any]] | None) -> NormalizedMetadata:
        source: dict[str, dict[str, Any]] = {}
        index_entries: list[dict[str, Any]] = []

        if len(entries or []) > 50:
            raise ValueError("A document cannot have more than 50 custom metadata fields")

        for raw in entries or []:
            key = str(raw.get("key") or "").strip().lower()
            metadata_type = str(raw.get("type") or "")
            value = raw.get("value")
            if not key:
                raise ValueError("Custom metadata key is required")
            if key in self.PROTECTED_KEYS or key.startswith("chunk_embedding_"):
                raise ValueError(f"Custom metadata key '{key}' is protected")
            if not self.KEY_PATTERN.fullmatch(key):
                raise ValueError(
                    f"Custom metadata key '{key}' must use lowercase letters, numbers, and underscores"
                )
            if key in source:
                raise ValueError(f"Custom metadata key '{key}' is duplicate")
            if metadata_type not in self.VALUE_FIELDS:
                raise ValueError(f"Unsupported custom metadata type for '{key}': {metadata_type}")

            normalized_value = self._normalize_value(key, metadata_type, value)
            source[key] = {"type": metadata_type, "value": normalized_value}
            index_entry = {
                "key": key,
                "type": metadata_type,
                self.VALUE_FIELDS[metadata_type]: normalized_value,
            }
            if metadata_type == "string":
                index_entry["string_value_text"] = normalized_value
            index_entries.append(index_entry)

        return NormalizedMetadata(source=source, index_entries=index_entries)

    def entries_from_mapping(self, values: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Convert trusted Langflow/custom maps to the typed public representation."""
        entries: list[dict[str, Any]] = []
        for key, raw_value in (values or {}).items():
            canonical_key = str(key).strip().lower()
            if canonical_key in self.PROTECTED_KEYS or raw_value is None:
                continue
            if isinstance(raw_value, dict) and {"type", "value"} <= raw_value.keys():
                entries.append(
                    {
                        "key": canonical_key,
                        "type": raw_value["type"],
                        "value": raw_value["value"],
                    }
                )
                continue
            sample = raw_value[0] if isinstance(raw_value, list) and raw_value else raw_value
            if isinstance(sample, bool):
                metadata_type = "boolean"
            elif isinstance(sample, (int, float)):
                metadata_type = "number"
            elif isinstance(sample, str):
                metadata_type = "string"
            else:
                continue
            entries.append({"key": canonical_key, "type": metadata_type, "value": raw_value})
        return entries

    def compile_expression(
        self,
        expression: dict[str, Any] | None,
        field_types: dict[str, str],
    ) -> dict[str, Any]:
        """Validate a public metadata expression and compile it to OpenSearch DSL."""
        if not expression:
            return {"match_all": {}}
        if self._condition_count(expression) > 50:
            raise ValueError("Custom metadata filters cannot exceed 50 conditions")
        return self._compile_node(expression, field_types, depth=0)

    def _condition_count(self, node: dict[str, Any]) -> int:
        conditions = node.get("conditions")
        if not isinstance(conditions, list):
            return 1
        return sum(
            self._condition_count(condition)
            for condition in conditions
            if isinstance(condition, dict)
        )

    def _compile_node(
        self,
        node: dict[str, Any],
        field_types: dict[str, str],
        *,
        depth: int,
    ) -> dict[str, Any]:
        if depth > 5:
            raise ValueError("Custom metadata filter nesting cannot exceed 5 levels")
        if "conditions" in node:
            op = str(node.get("op") or "and").lower()
            if op not in {"and", "or"}:
                raise ValueError("Custom metadata filter group op must be 'and' or 'or'")
            conditions = node.get("conditions")
            if not isinstance(conditions, list) or not conditions:
                raise ValueError("Custom metadata filter group requires conditions")
            compiled = [
                self._compile_node(item, field_types, depth=depth + 1) for item in conditions
            ]
            if op == "and":
                return {"bool": {"must": compiled}}
            return {"bool": {"should": compiled, "minimum_should_match": 1}}

        key = str(node.get("key") or "").strip().lower()
        if key not in field_types:
            raise ValueError(f"Unknown custom metadata key '{key}'")
        metadata_type = field_types[key]
        operator = str(node.get("operator") or "").lower()
        return self._compile_condition(key, metadata_type, operator, node.get("value"))

    def _compile_condition(
        self,
        key: str,
        metadata_type: str,
        operator: str,
        value: Any,
    ) -> dict[str, Any]:
        value_field = self.VALUE_FIELDS.get(metadata_type)
        if value_field is None:
            raise ValueError(f"Unsupported registered type for '{key}': {metadata_type}")
        key_clause = {"term": {"metadata_entries.key": key}}
        field = f"metadata_entries.{value_field}"

        positive: dict[str, Any]
        if operator in {"exists", "not_exists"}:
            positive = {"nested": {"path": "metadata_entries", "query": key_clause}}
            return self._negate(positive) if operator == "not_exists" else positive
        if operator in {"equals", "not_equals"}:
            self._require_scalar(key, operator, value)
            normalized = self._normalize_value(key, metadata_type, value)
            value_clause = {"term": {field: normalized}}
        elif operator in {"in", "not_in"}:
            if not isinstance(value, list) or not value:
                raise ValueError(f"Operator '{operator}' for '{key}' requires a non-empty list")
            normalized = self._normalize_value(key, metadata_type, value)
            value_clause = {"terms": {field: normalized}}
        elif operator in {"contains", "not_contains"}:
            if metadata_type != "string":
                raise ValueError(f"Operator '{operator}' is only valid for string metadata")
            self._require_scalar(key, operator, value)
            normalized = self._normalize_value(key, metadata_type, value)
            value_clause = {"match_phrase": {"metadata_entries.string_value_text": normalized}}
        elif operator in {"gt", "gte", "lt", "lte"}:
            if metadata_type not in {"number", "date"}:
                raise ValueError(f"Operator '{operator}' requires number or date metadata")
            self._require_scalar(key, operator, value)
            normalized = self._normalize_value(key, metadata_type, value)
            value_clause = {"range": {field: {operator: normalized}}}
        elif operator == "between":
            if metadata_type not in {"number", "date"} or not isinstance(value, dict):
                raise ValueError("Operator 'between' requires number or date bounds")
            bounds = {
                bound: self._normalize_value(key, metadata_type, bound_value)
                for bound, bound_value in value.items()
                if bound in {"gt", "gte", "lt", "lte"}
            }
            if not bounds:
                raise ValueError("Operator 'between' requires at least one bound")
            value_clause = {"range": {field: bounds}}
        else:
            raise ValueError(f"Unsupported custom metadata operator '{operator}'")

        positive = {
            "nested": {
                "path": "metadata_entries",
                "query": {"bool": {"must": [key_clause, value_clause]}},
            }
        }
        if operator in {"not_equals", "not_in", "not_contains"}:
            return self._negate(positive)
        return positive

    @staticmethod
    def _negate(clause: dict[str, Any]) -> dict[str, Any]:
        return {"bool": {"must_not": [clause]}}

    @staticmethod
    def _require_scalar(key: str, operator: str, value: Any) -> None:
        if isinstance(value, (list, dict)):
            raise ValueError(f"Operator '{operator}' for '{key}' requires a scalar value")

    @staticmethod
    def _normalize_value(key: str, metadata_type: str, value: Any) -> Any:
        values = value if isinstance(value, list) else [value]
        if len(values) > 100:
            raise ValueError(f"Custom metadata '{key}' cannot contain more than 100 values")
        normalized: list[Any] = []
        for item in values:
            if metadata_type == "string":
                if not isinstance(item, str):
                    raise ValueError(f"Custom metadata '{key}' must be a string")
                if len(item) > 2048:
                    raise ValueError(f"Custom metadata '{key}' exceeds 2048 characters")
                normalized.append(item)
            elif metadata_type == "number":
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError(f"Custom metadata '{key}' must be a number")
                normalized.append(item)
            elif metadata_type == "boolean":
                if not isinstance(item, bool):
                    raise ValueError(f"Custom metadata '{key}' must be a boolean")
                normalized.append(item)
            else:
                if not isinstance(item, str):
                    raise ValueError(f"Custom metadata '{key}' must be an ISO date")
                try:
                    date.fromisoformat(item)
                except ValueError as exc:
                    raise ValueError(f"Custom metadata '{key}' must be an ISO date") from exc
                normalized.append(item)
        return normalized if isinstance(value, list) else normalized[0]


CUSTOM_METADATA_MAPPING: dict[str, Any] = {
    "type": "nested",
    "properties": {
        "key": {"type": "keyword"},
        "type": {"type": "keyword"},
        "string_value": {"type": "keyword"},
        "string_value_text": {"type": "text"},
        "number_value": {"type": "double"},
        "date_value": {"type": "date"},
        "boolean_value": {"type": "boolean"},
    },
}
