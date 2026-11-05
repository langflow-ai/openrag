"""
Utility functions for constructing OpenSearch queries consistently.
"""

import re


def build_filename_query(filename: str) -> dict:
    """
    Build a standardized query for finding documents by filename.

    Args:
        filename: The exact filename to search for

    Returns:
        A dict containing the OpenSearch query body
    """
    return {"term": {"filename": filename}}


def build_filename_search_body(
    filename: str, size: int = 1, source: bool | list[str] = False
) -> dict:
    """
    Build a complete search body for checking if a filename exists.

    Args:
        filename: The exact filename to search for
        size: Number of results to return (default: 1)
        source: Whether to include source fields, or list of specific fields to include (default: False)

    Returns:
        A dict containing the complete OpenSearch search body
    """
    return {"query": build_filename_query(filename), "size": size, "_source": source}


def build_existing_filenames_agg_body(filenames: list[str]) -> dict:
    """
    build a search body for checking which of the given filenames currently have indexed chunks

    Args:
        filenames: Filenames to check for existence

    Returns:
        A dict containing the complete OpenSearch search body
    """
    return {
        "query": {"terms": {"filename": filenames}},
        "size": 0,
        "aggs": {"filenames": {"terms": {"field": "filename", "size": len(filenames)}}},
    }


def build_owned_filename_query(filename: str, owner: str) -> dict:
    """Build a query for chunks with a filename owned by a specific user."""
    return {
        "bool": {
            "filter": [
                build_filename_query(filename),
                {"term": {"owner": owner}},
            ]
        }
    }


def build_anonymous_filename_query(filename: str) -> dict:
    """Build a query for ownerless chunks with a specific filename."""
    return {
        "bool": {
            "filter": [
                build_filename_query(filename),
                {"bool": {"must_not": {"exists": {"field": "owner"}}}},
            ]
        }
    }


def build_owner_or_shared_filter(owner: str) -> dict:
    """Build the owner-scope clause covering a user's own chunks AND shared ones.

    Matches ``owner == owner`` OR the ``owner`` field being absent.  The
    ownerless branch is what keeps replace/cleanup working on documents ingested
    with the COS "make available to all users" toggle, which indexes chunks
    without an owner at all; naming the current user in the other branch keeps
    another user's *private* document — merely visible to us via allowed_users
    DLS — out of scope.

    This is the deletion boundary for anything we have already matched by a
    stable identity (filename alias, connector file id): both layouts are ours
    to replace, neither is someone else's to remove.
    """
    return {
        "bool": {
            "should": [
                {"term": {"owner": owner}},
                {"bool": {"must_not": {"exists": {"field": "owner"}}}},
            ],
            "minimum_should_match": 1,
        }
    }


def build_replace_filename_query(filename: str, owner: str) -> dict:
    """Build a delete-scope query for replace_duplicates that covers both private
    and shared (ownerless) chunks with this filename.

    Matches chunks where filename matches AND (owner == current user OR owner
    field is absent) — see build_owner_or_shared_filter.  Combining both cases
    is necessary because the same filename may have been previously ingested as
    shared (no owner field) and is now being replaced by the same user.
    """
    return {
        "bool": {
            "filter": [
                build_filename_query(filename),
                build_owner_or_shared_filter(owner),
            ]
        }
    }


_PARTIAL_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:T(?P<hm>\d{2}:\d{2}))?(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)


def normalize_date_bound(value: str) -> str:
    """Spell out the seconds a bound omits.

    API validation reads ``2026-10-10`` as midnight and ``…T10:30`` as 10:30:00,
    but OpenSearch expands the missing parts of an ``lte`` bound to the end of
    that day or minute. Sending the explicit instant keeps both in agreement.
    Full timestamps are returned unchanged.
    """
    match = _PARTIAL_TIMESTAMP_RE.match(value)
    if match is None:
        return value
    return f"{match['date']}T{match['hm'] or '00:00'}:00{match['tz'] or 'Z'}"


def build_date_range_query(
    field: str, gte: str | None = None, lte: str | None = None
) -> dict | None:
    """
    Build a date range query clause for OpenSearch.

    Args:
        field: The date field name to filter on (e.g. 'created_time')
        gte: Lower bound ISO-8601 string (inclusive)
        lte: Upper bound ISO-8601 string (inclusive)

    Returns:
        A dict containing {"range": {field: {...}}} or None if both bounds are None.
        Bounds that omit seconds are sent as explicit instants (see normalize_date_bound).
    """
    range_bounds: dict[str, str] = {}
    if gte is not None:
        range_bounds["gte"] = normalize_date_bound(gte)
    if lte is not None:
        range_bounds["lte"] = normalize_date_bound(lte)
    if not range_bounds:
        return None
    return {"range": {field: range_bounds}}


_INNER_KNN_FILTER_ENGINES = frozenset({"lucene", "faiss", "jvector"})


def supports_inner_knn_filter(field_def: dict | None) -> bool:
    """True when the vector field's engine supports a filter inside the k-NN clause."""
    method = field_def.get("method") if isinstance(field_def, dict) else None
    engine = method.get("engine") if isinstance(method, dict) else None
    return isinstance(engine, str) and engine.lower() in _INNER_KNN_FILTER_ENGINES


def build_exact_filtered_knn_query(
    field_name: str, field_def: dict | None, vector: list[float], filter_clauses: list[dict]
) -> dict:
    """Exact k-NN scoring over only the documents matching *filter_clauses*.

    Used for engines that cannot filter inside the k-NN clause (nmslib), so the
    filter is applied before neighbours are chosen rather than after.
    """
    method = field_def.get("method") if isinstance(field_def, dict) else None
    space_type = method.get("space_type") if isinstance(method, dict) else None
    return {
        "script_score": {
            "query": {"bool": {"filter": [{"exists": {"field": field_name}}, *filter_clauses]}},
            "script": {
                "source": "knn_score",
                "lang": "knn",
                "params": {
                    "field": field_name,
                    "query_value": vector,
                    "space_type": space_type or "l2",
                },
            },
        }
    }


FILTER_FIELD_MAPPING = {
    "data_sources": "filename",
    "document_types": "mimetype",
    "owners": "owner",
    "connector_types": "connector_type",
}


def build_filter_clauses(
    filters: dict | None, *, empty_list_matches_nothing: bool = False
) -> list[dict]:
    """
    Convert request filters into OpenSearch filter clauses.

    List-valued filters become term/terms clauses on the mapped field.
    ``created_after``/``created_before`` become one inclusive ``indexed_time``
    range clause.

    Args:
        filters: Frontend filter dict (may be None/empty).
        empty_list_matches_nothing: When True an empty list matches no documents
            (search behavior); when False it is ignored (chat/nudges behavior).
    """
    clauses: list[dict] = []
    if not filters:
        return clauses

    for filter_key, values in filters.items():
        if values is None or not isinstance(values, list):
            continue
        field_name = FILTER_FIELD_MAPPING.get(filter_key, filter_key)
        if len(values) == 0:
            if empty_list_matches_nothing:
                clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
        elif len(values) == 1:
            clauses.append({"term": {field_name: values[0]}})
        else:
            clauses.append({"terms": {field_name: values}})

    date_clause = build_date_range_query(
        "indexed_time",
        gte=filters.get("created_after") or None,
        lte=filters.get("created_before") or None,
    )
    if date_clause is not None:
        clauses.append(date_clause)
    return clauses
