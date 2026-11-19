"""Field discovery, suggestion and validation for restored datasets.

Field names are always dotted ``_source`` paths. Multi-fields such as
``title.keyword`` are *not* source paths and are never listed. Fields below a
``nested`` mapping are excluded in v1 (they cannot be queried at the root).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TEXT_TYPES = frozenset({"text", "match_only_text", "search_as_you_type"})
KEYWORD_TYPES = frozenset({"keyword", "constant_keyword", "wildcard"})
STRING_TYPES = TEXT_TYPES | KEYWORD_TYPES
VECTOR_TYPES = frozenset({"knn_vector", "dense_vector"})

_MAX_TEXT_FIELDS = 10
_SUGGEST_TEXT_FIELDS = 5
_TITLE_NAMES = ("title", "name", "headline", "subject", "filename", "file_name")
_URL_NAMES = ("url", "source_url", "link", "uri", "href", "wikipedia_url")
_RETRIEVAL_KEYS = frozenset({"mode", "vector_field", "provider", "model", "dims"})
_FIELD_MAP_KEYS = frozenset({"text_fields", "title_field", "url_field"})
_MAX_DEPTH = 20


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str
    dims: int | None = None
    engine: str | None = None

    @property
    def is_vector(self) -> bool:
        return self.type in VECTOR_TYPES

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type, "dims": self.dims}
        if self.is_vector:
            out["engine"] = self.engine
        return out


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _walk(properties: Mapping[str, Any], prefix: str, out: list[FieldInfo], depth: int) -> None:
    if depth > _MAX_DEPTH:
        return
    for name, cfg in properties.items():
        if not isinstance(cfg, Mapping):
            continue
        path = f"{prefix}{name}"
        field_type = cfg.get("type")
        if field_type == "nested":
            # v1 searches ``_source`` paths with root-level queries and plain-object
            # traversal; neither reaches inside nested arrays, so nested subtrees are
            # neither discoverable nor valid. Plain ``object`` paths are unaffected.
            continue
        children = cfg.get("properties")
        if isinstance(children, Mapping):
            _walk(children, f"{path}.", out, depth + 1)
        if not isinstance(field_type, str):
            continue
        if field_type in ("object", "nested", "flat_object", "join"):
            continue
        engine = None
        dims = None
        if field_type in VECTOR_TYPES:
            dims = _int_or_none(cfg.get("dimension", cfg.get("dims")))
            method = cfg.get("method")
            engine_raw = method.get("engine") if isinstance(method, Mapping) else cfg.get("engine")
            engine = engine_raw if isinstance(engine_raw, str) else None
        out.append(FieldInfo(path, field_type, dims, engine))


def flatten_mapping(mappings: Mapping[str, Any]) -> list[FieldInfo]:
    """Leaf fields of a mapping as dotted ``_source`` paths (multi-fields excluded)."""
    body: Mapping[str, Any] = mappings or {}
    if "properties" not in body and len(body) == 1:
        inner = next(iter(body.values()))
        if isinstance(inner, Mapping):
            body = inner
    props = body.get("properties")
    out: list[FieldInfo] = []
    if isinstance(props, Mapping):
        _walk(props, "", out, 0)
    return sorted(out, key=lambda f: f.name)


def vector_fields(fields: Sequence[FieldInfo]) -> list[FieldInfo]:
    return [f for f in fields if f.is_vector]


def _lookup(source: Any, dotted: str) -> Any:
    current = source
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _average_length(samples: Sequence[Mapping[str, Any]], name: str) -> float:
    lengths = [len(v) for s in samples if isinstance(v := _lookup(s, name), str)]
    return sum(lengths) / len(lengths) if lengths else 0.0


def suggest_field_map(
    fields: Sequence[FieldInfo], samples: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Heuristic ``{"text_fields", "title_field", "url_field"}`` (reviewed by the user)."""
    by_name = {f.name: f for f in fields}

    def pick(candidates: tuple[str, ...], allowed: frozenset[str]) -> str | None:
        lowered = {name.lower(): name for name, f in by_name.items() if f.type in allowed}
        for candidate in candidates:
            if candidate in lowered:
                return lowered[candidate]
        for name, f in by_name.items():
            if f.type in allowed and name.rsplit(".", 1)[-1].lower() in candidates:
                return name
        return None

    url_field = pick(_URL_NAMES, STRING_TYPES)
    if url_field is None:
        for f in fields:
            if f.type in KEYWORD_TYPES and any(
                isinstance(v := _lookup(s, f.name), str) and v.startswith(("http://", "https://"))
                for s in samples
            ):
                url_field = f.name
                break
    title_field = pick(_TITLE_NAMES, STRING_TYPES)

    text = [f.name for f in fields if f.type in TEXT_TYPES and f.name != url_field]
    if not text:
        text = [f.name for f in fields if f.type in KEYWORD_TYPES and f.name not in (url_field,)]
    text.sort(key=lambda name: (-_average_length(samples, name), name))
    return {
        "text_fields": text[:_SUGGEST_TEXT_FIELDS],
        "title_field": title_field,
        "url_field": url_field,
    }


def _check_string_field(
    label: str, value: Any, by_name: Mapping[str, FieldInfo], errors: list[str]
) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a field name")
        return
    field = by_name.get(value)
    if field is None:
        errors.append(
            f"{label} '{value}' is not a field of this dataset "
            "(use the source field path; fields inside nested mappings are not supported)"
        )
    elif field.type not in STRING_TYPES:
        errors.append(f"{label} '{value}' must be a text or keyword field")


def validate_field_map(field_map: Any, fields: Sequence[FieldInfo]) -> list[str]:
    """Validation messages for a field map; an empty list means valid."""
    if not isinstance(field_map, Mapping):
        return ["field_map must be an object"]
    by_name = {f.name: f for f in fields}
    errors: list[str] = []
    unknown = sorted(set(field_map) - _FIELD_MAP_KEYS)
    if unknown:
        errors.append(f"unknown field_map keys: {', '.join(map(str, unknown))}")
    text_fields = field_map.get("text_fields")
    if not isinstance(text_fields, list) or not text_fields:
        errors.append("text_fields must list at least one field")
    elif len(text_fields) > _MAX_TEXT_FIELDS:
        errors.append(f"text_fields may list at most {_MAX_TEXT_FIELDS} fields")
    else:
        if len(set(map(str, text_fields))) != len(text_fields):
            errors.append("text_fields must not contain duplicates")
        for name in text_fields:
            _check_string_field("text_fields entry", name, by_name, errors)
    for key in ("title_field", "url_field"):
        value = field_map.get(key)
        if value is not None:
            _check_string_field(key, value, by_name, errors)
    return errors


def default_retrieval() -> dict[str, Any]:
    return {"mode": "lexical"}


def validate_retrieval(
    retrieval: Any, fields: Sequence[FieldInfo], available_models: set[str]
) -> list[str]:
    """Validate a ``{mode, vector_field, provider, model, dims}`` retrieval config."""
    if not isinstance(retrieval, Mapping):
        return ["retrieval must be an object"]
    errors: list[str] = []
    unknown = sorted(set(retrieval) - _RETRIEVAL_KEYS)
    if unknown:
        errors.append(f"unknown retrieval keys: {', '.join(map(str, unknown))}")
    mode = retrieval.get("mode")
    if mode not in ("lexical", "hybrid"):
        errors.append("retrieval mode must be 'lexical' or 'hybrid'")
        return errors
    if mode == "lexical":
        return errors

    by_name = {f.name: f for f in fields}
    vector_name = retrieval.get("vector_field")
    field = by_name.get(vector_name) if isinstance(vector_name, str) else None
    if field is None or not field.is_vector:
        errors.append(
            "hybrid retrieval needs vector_field to be a knn_vector or dense_vector field"
        )
    provider, model = retrieval.get("provider"), retrieval.get("model")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        errors.append("hybrid retrieval needs provider and model")
    elif f"{provider}:{model}" not in available_models:
        errors.append("the selected embedding model is not available")
    dims = retrieval.get("dims")
    if not isinstance(dims, int) or isinstance(dims, bool) or dims < 1:
        errors.append("hybrid retrieval needs the embedding dimension (dims)")
    elif field is not None and field.is_vector and field.dims is not None and field.dims != dims:
        errors.append(f"dims ({dims}) does not match the vector field dimension ({field.dims})")
    return errors
