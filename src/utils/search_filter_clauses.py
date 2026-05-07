"""
Build OpenSearch bool filter clauses from UI search / knowledge filter payloads.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _clause_from_data_source_refs(refs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """OR across selected sources; each source matches filename OR document_id when both exist."""
    per_doc: List[Dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        fn = (ref.get("filename") or "").strip()
        did = (ref.get("document_id") or "").strip() or None
        inner: List[Dict[str, Any]] = []
        if fn:
            inner.append({"term": {"filename": fn}})
        if did:
            inner.append({"term": {"document_id": did}})
        if not inner:
            continue
        if len(inner) == 1:
            per_doc.append(inner[0])
        else:
            per_doc.append(
                {
                    "bool": {
                        "should": inner,
                        "minimum_should_match": 1,
                    }
                }
            )
    if not per_doc:
        return None
    if len(per_doc) == 1:
        return per_doc[0]
    return {
        "bool": {
            "should": per_doc,
            "minimum_should_match": 1,
        }
    }


def build_data_source_opensearch_clause(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build a single filter clause for the source dimension, or None if unset / wildcard.

    Uses ``data_source_refs`` when present (filename + optional document_id per source).
    Refs are evaluated first so they still apply when ``data_sources`` is ``["*"]``,
    empty, or otherwise inconsistent with the saved ref list.

    Falls back to legacy ``data_sources`` as exact ``filename`` terms.
    """
    ds = filters.get("data_sources")
    refs_raw = filters.get("data_source_refs")

    if refs_raw and isinstance(refs_raw, list) and len(refs_raw) > 0:
        norm_refs: List[Dict[str, Any]] = []
        for item in refs_raw:
            if isinstance(item, dict):
                norm_refs.append(item)
        clause = _clause_from_data_source_refs(norm_refs)
        if clause is not None:
            return clause

    if not ds or not isinstance(ds, list) or "*" in ds:
        return None

    names = [x for x in ds if isinstance(x, str) and x.strip() and x != "*"]

    # Legacy: filename list only
    if not names:
        return None
    if len(names) == 1:
        return {"term": {"filename": names[0]}}
    return {"terms": {"filename": names}}


def build_user_filter_clauses(filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Full set of OpenSearch filter clauses for user-selected facets (knowledge search).
    Skips unknown keys. Handles ``data_sources`` + ``data_source_refs`` together.
    """
    if not filters:
        return []

    filter_clauses: List[Dict[str, Any]] = []

    src = build_data_source_opensearch_clause(filters)
    if src is not None:
        filter_clauses.append(src)

    field_mapping = {
        "document_types": "mimetype",
        "owners": "owner",
        "connector_types": "connector_type",
    }

    for filter_key, values in filters.items():
        if filter_key in ("data_sources", "data_source_refs"):
            continue
        field_name = field_mapping.get(filter_key)
        if not field_name:
            continue
        if values is None or not isinstance(values, list):
            continue

        if len(values) == 0:
            filter_clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
        elif len(values) == 1:
            filter_clauses.append({"term": {field_name: values[0]}})
        else:
            filter_clauses.append({"terms": {field_name: values}})

    return filter_clauses
