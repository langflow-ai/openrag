"""
Utility functions for constructing OpenSearch queries consistently.
"""


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
