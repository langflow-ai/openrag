"""Shared filename-existence checks against the documents index.

Duplicate-filename decisions happen at several altitudes — the UI pre-check
endpoints, the API sync pre-filters, and the per-file processor backstop.
They must share one query semantic or the layers can disagree about what
counts as a duplicate. Every caller goes through this module: one terms
aggregation over exact ``filename`` keywords, with alias expansion via
``get_filename_aliases`` where a single logical filename is being checked.

The aggregation matters: collecting filenames from search *hits* undercounts
when a many-chunk document crowds other matches out of the hits window.
"""

from collections.abc import Iterable

from utils.file_utils import get_filename_aliases
from utils.opensearch_queries import build_existing_filenames_agg_body


async def find_existing_filenames(
    candidates: Iterable[str],
    opensearch_client,
    index: str,
) -> set[str]:
    """Return the subset of exact candidate filenames that have at least one
    indexed chunk visible to this client.

    Callers own alias expansion (pass every variant that should count) and
    error handling — OpenSearch exceptions propagate.
    """
    unique = sorted({c for c in candidates if c})
    if not unique:
        return set()
    response = await opensearch_client.search(
        index=index,
        body=build_existing_filenames_agg_body(unique),
    )
    buckets = response.get("aggregations", {}).get("filenames", {}).get("buckets", [])
    return {bucket["key"] for bucket in buckets if bucket.get("key")}


async def filename_exists(
    filename: str,
    opensearch_client,
    index: str,
) -> bool:
    """True when this filename — or any of its ingestion aliases — has indexed
    chunks visible to this client."""
    aliases = get_filename_aliases(filename)
    if not aliases:
        return False
    return bool(await find_existing_filenames(aliases, opensearch_client, index))
