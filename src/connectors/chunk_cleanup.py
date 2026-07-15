"""Single deletion path for a connector file's indexed chunks.

Deletion propagation has multiple *triggers* — orphan reconciliation (file
missing from a full remote listing), per-file 404 cleanup during sync, rename
cleanup — but exactly one deletion *semantic*, owned here:

* Chunks are matched by the stable connector file id against BOTH id layouts:
  the standard ingest path stores it in ``connector_file_id`` (``document_id``
  holds the content hash), the Langflow path stores it in ``document_id``.
  Matching a single field misses chunks from the other layout.
* Optionally owner-scoped: ``owner_user_id`` restricts to that owner's chunks;
  ``shared=True`` targets ownerless (instance-shared) chunks instead.
* DLS-safe: visible chunk ``_id``s are enumerated with the caller's
  (user-scoped) client, then deleted individually with the trusted backend
  write client — ``delete_by_query`` is silently no-opped under DLS.
"""

from collections.abc import Iterable
from typing import Any


def build_connector_file_chunks_query(
    file_ids: Iterable[str],
    *,
    owner_user_id: str | None = None,
    shared: bool = False,
    keep_filenames: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Query matching every chunk of the given connector file ids.

    ``keep_filenames`` excludes chunks indexed under those names — used by
    rename cleanup to drop only the stale old-name chunks of a file id.
    """
    ids = [fid for fid in file_ids if fid]
    filters: list[dict[str, Any]] = [
        {
            "bool": {
                "should": [
                    {"terms": {"document_id": ids}},
                    {"terms": {"connector_file_id": ids}},
                    # Some indices predate the explicit keyword mapping for
                    # connector_file_id, so it was dynamically mapped as
                    # analyzed text with a .keyword multi-field.
                    {"terms": {"connector_file_id.keyword": ids}},
                ],
                "minimum_should_match": 1,
            }
        }
    ]
    if shared:
        filters.append({"bool": {"must_not": {"exists": {"field": "owner"}}}})
    elif owner_user_id:
        filters.append({"term": {"owner": owner_user_id}})
    query: dict[str, Any] = {"bool": {"filter": filters}}
    keep = [name for name in (keep_filenames or []) if name]
    if keep:
        query["bool"]["must_not"] = [{"terms": {"filename": keep}}]
    return query


async def delete_connector_file_chunks(
    file_ids: Iterable[str],
    opensearch_client,
    *,
    owner_user_id: str | None = None,
    shared: bool = False,
    keep_filenames: Iterable[str] | None = None,
    refresh: bool = False,
) -> int:
    """Delete the indexed chunks of the given connector file ids.

    Returns the number of chunks deleted. Raises on infrastructure failure
    (missing write client, OpenSearch errors) — callers that must never fail
    their surrounding task wrap this in their own best-effort handling.
    """
    from config.settings import clients, get_index_name
    from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids

    ids = [fid for fid in (file_ids or []) if fid]
    if not ids:
        return 0

    write_client = clients.opensearch
    if write_client is None:
        raise RuntimeError("Backend OpenSearch write client is unavailable")

    chunk_ids = await collect_visible_document_ids(
        opensearch_client,
        index=get_index_name(),
        query=build_connector_file_chunks_query(
            ids,
            owner_user_id=owner_user_id,
            shared=shared,
            keep_filenames=keep_filenames,
        ),
    )
    return await delete_document_ids(
        write_client,
        index=get_index_name(),
        document_ids=chunk_ids,
        refresh=refresh,
    )
