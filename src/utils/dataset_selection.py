"""Which imported datasets a request may search.

A selection is one of three things:

* ``None``: no restriction, every dataset the caller can see (missing key,
  ``None``, ``"*"`` or ``["*"]``).
* ``[]``: explicitly none. An empty list is a choice, not an absence.
* ``["id", ...]``: exactly those datasets, if the caller can see them.

Visibility always wins: a selection can only narrow what the caller can see,
and so can a model-supplied tool argument.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DATASETS_KEY = "datasets"
_ALL = "*"


def normalize_selection(value: Any) -> list[str] | None:
    """Return ``None`` for "all visible", else the deduplicated id list.

    Raises ``ValueError`` for anything that is not ``None``, ``"*"`` or a list of
    non-empty strings, so a malformed selection never widens into "all".
    """
    if value is None:
        return None
    if isinstance(value, str):
        if value == _ALL:
            return None
        raise ValueError('datasets must be "*" or a list of dataset ids')
    if not isinstance(value, list | tuple):
        raise ValueError('datasets must be "*" or a list of dataset ids')
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("dataset ids must be non-empty strings")
        if item == _ALL:
            return None
        if item not in ids:
            ids.append(item)
    return ids


def _present(filters: dict[str, Any] | None) -> bool:
    return isinstance(filters, dict) and DATASETS_KEY in filters


def resolve_v1_selection(
    *,
    body_has_datasets: bool,
    body_datasets: Any,
    inline_filters: dict[str, Any] | None,
    saved_filters: dict[str, Any] | None,
) -> list[str] | None:
    """Pick the selection for ``/v1/search`` by precedence.

    ``body.datasets`` (when sent) beats ``filters["datasets"]`` (when the key is
    present) beats the saved filter's ``datasets`` (when the key is present) beats
    "all". Presence decides, not truthiness: ``datasets: []`` overrides.
    """
    if body_has_datasets:
        return normalize_selection(body_datasets)
    if _present(inline_filters):
        return normalize_selection((inline_filters or {})[DATASETS_KEY])
    if _present(saved_filters):
        return normalize_selection((saved_filters or {})[DATASETS_KEY])
    return None


def effective_ids(
    selection: list[str] | None,
    visible_ids: Iterable[str],
    tool_requested: list[str] | None = None,
) -> list[str]:
    """``visible ∩ selection ∩ tool_requested``, in visibility order.

    ``selection=None`` keeps every visible id; ``tool_requested=None`` adds no
    further narrowing. An unusable ``tool_requested`` (not a list of strings)
    narrows to nothing rather than being ignored.
    """
    visible = list(dict.fromkeys(visible_ids))
    if selection is not None:
        allowed = set(selection)
        visible = [dataset_id for dataset_id in visible if dataset_id in allowed]
    if tool_requested is not None:
        try:
            requested = normalize_selection(tool_requested)
        except ValueError:
            return []
        if requested is not None:
            wanted = set(requested)
            visible = [dataset_id for dataset_id in visible if dataset_id in wanted]
    return visible
