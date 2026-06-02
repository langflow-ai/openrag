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
