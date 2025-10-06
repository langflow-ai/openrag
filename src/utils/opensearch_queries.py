"""
Utility functions for constructing OpenSearch queries consistently.
"""
from typing import Union, List


def build_filename_query(filename: str) -> dict:
    """
    Build a standardized query for finding documents by filename.

    Args:
        filename: The exact filename to search for

    Returns:
        A dict containing the OpenSearch query body
    """
    return {
        "term": {
            "filename": filename
        }
    }


def build_filename_search_body(filename: str, size: int = 1, source: Union[bool, List[str]] = False) -> dict:
    """
    Build a complete search body for checking if a filename exists.

    Args:
        filename: The exact filename to search for
        size: Number of results to return (default: 1)
        source: Whether to include source fields, or list of specific fields to include (default: False)

    Returns:
        A dict containing the complete OpenSearch search body
    """
    return {
        "query": build_filename_query(filename),
        "size": size,
        "_source": source
    }


def build_filename_delete_body(filename: str) -> dict:
    """
    Build a delete-by-query body for removing all documents with a filename.

    Args:
        filename: The exact filename to delete

    Returns:
        A dict containing the OpenSearch delete-by-query body
    """
    return {
        "query": build_filename_query(filename)
    }
