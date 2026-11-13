"""Classify Microsoft Graph failures for the OneDrive and SharePoint connectors.

Only a positive "this item does not exist" answer may be treated as a deletion
at source: ``ConnectorFileProcessor`` deletes indexed chunks on
``FileNotFoundError``, and orphan reconciliation deletes ids missing from a
listing. Auth, throttling, server and network failures prove nothing about the
file and must propagate instead.
"""

import httpx

# Graph statuses that positively answer "the item is gone".
GRAPH_ITEM_MISSING_STATUSES = frozenset({404, 410})


def graph_error_status(exc: BaseException) -> int | None:
    """HTTP status of a failed Graph request, or None for non-HTTP failures."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def is_graph_item_missing(exc: BaseException) -> bool:
    """True only when Graph positively reported that the item does not exist."""
    return graph_error_status(exc) in GRAPH_ITEM_MISSING_STATUSES
