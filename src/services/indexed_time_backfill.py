"""One-shot repair: give every chunk of an ingest run the run's earliest indexed_time.

Before per-run timestamps, each Langflow ingest-callback batch stamped its own
``indexed_time``, so one file could carry several values and the Date Uploaded
sort (grouped by ``(indexed_time, filename)``) listed it as several rows.

Scope: this makes ``indexed_time`` uniform within an ``ingest_run_id``. It does
not merge different runs that share a filename, and chunks without an
``ingest_run_id`` are not touched.

Eligibility: a split run is deferred while its newest chunk (``max_t``) is
within ``LANGFLOW_INGEST_CALLBACK_TTL_SECONDS`` of now. This is an inactivity
precaution based on the configured token lifetime, not the run's actual token
expiry: expiry stops new callback requests being accepted, but a request
accepted just before expiry can still finish writing afterwards, so the cutoff
deliberately keys off the last observed write rather than ``min_t + TTL``. It
lowers the chance of rewriting a run that is still being ingested; it is not a
guarantee that no writes are in flight (that would need completion or
in-flight-write tracking, which is out of scope here).

Deferred runs, like any failed or partial pass, are retried on the next boot;
the migration is only marked done after a complete clean pass.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from config.settings import LANGFLOW_INGEST_CALLBACK_TTL_SECONDS, clients, get_index_name
from db.migrations_runtime import _already_done, _mark_done
from utils.logging_config import get_logger

logger = get_logger(__name__)

MIGRATION_NAME = "indexed_time_per_ingest_run_v1"
_PAGE_SIZE = 500

_FIX_SCRIPT = """
def t = params.times[ctx._source.ingest_run_id];
if (t == null || t.equals(ctx._source.indexed_time)) { ctx.op = 'noop'; }
else { ctx._source.indexed_time = t; }
"""


def _scan_body(after_key: dict[str, Any] | None) -> dict[str, Any]:
    composite: dict[str, Any] = {
        "size": _PAGE_SIZE,
        "sources": [{"run": {"terms": {"field": "ingest_run_id"}}}],
    }
    if after_key:
        composite["after"] = after_key
    return {
        "size": 0,
        "query": {"exists": {"field": "ingest_run_id"}},
        "aggs": {
            "runs": {
                "composite": composite,
                "aggs": {
                    "min_t": {"min": {"field": "indexed_time"}},
                    "max_t": {"max": {"field": "indexed_time"}},
                    "earliest": {
                        "top_hits": {
                            "size": 1,
                            "_source": ["indexed_time"],
                            "sort": [{"indexed_time": {"order": "asc"}}],
                        }
                    },
                },
            }
        },
    }


def _select_runs(buckets: list[dict[str, Any]], cutoff_ms: float) -> tuple[dict[str, str], int]:
    """Return ({run_id: earliest indexed_time string}, deferred_count)."""
    times: dict[str, str] = {}
    deferred = 0
    for bucket in buckets:
        min_t = bucket.get("min_t", {}).get("value")
        max_t = bucket.get("max_t", {}).get("value")
        if min_t is None or min_t == max_t:
            continue
        if max_t >= cutoff_ms:  # recent write activity: see module docstring
            deferred += 1
            continue
        hits = bucket.get("earliest", {}).get("hits", {}).get("hits", [])
        target = hits[0].get("_source", {}).get("indexed_time") if hits else None
        if target:
            times[str(bucket["key"]["run"])] = target
    return times, deferred


async def _run_backfill(client: Any, index_name: str) -> dict[str, int] | None:
    """Scan and repair. Returns counts, or None when the pass was incomplete."""
    stats = {"fixed": 0, "deferred": 0, "updated": 0, "conflicts": 0, "failures": 0}
    if not await client.indices.exists(index=index_name):
        return stats

    cutoff_ms = (time.time() - LANGFLOW_INGEST_CALLBACK_TTL_SECONDS) * 1000
    after_key: dict[str, Any] | None = None
    while True:
        response = await client.search(index=index_name, body=_scan_body(after_key))
        if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
            logger.warning("Indexed-time backfill scan was partial", index_name=index_name)
            return None
        agg = response.get("aggregations", {}).get("runs", {})
        times, deferred = _select_runs(agg.get("buckets", []), cutoff_ms)
        stats["deferred"] += deferred

        if times:
            result = await client.update_by_query(
                index=index_name,
                body={
                    "query": {"terms": {"ingest_run_id": list(times)}},
                    "script": {
                        "lang": "painless",
                        "source": _FIX_SCRIPT,
                        "params": {"times": times},
                    },
                },
                conflicts="proceed",
                wait_for_completion=True,
                request_timeout=300,
            )
            if result.get("timed_out"):
                logger.warning("Indexed-time backfill update timed out", index_name=index_name)
                return None
            stats["fixed"] += len(times)
            stats["updated"] += int(result.get("updated", 0))
            stats["conflicts"] += int(result.get("version_conflicts", 0))
            stats["failures"] += len(result.get("failures", []))

        after_key = agg.get("after_key")
        if not after_key:
            break

    if stats["updated"] > 0:
        await client.indices.refresh(index=index_name)
    return stats


async def run_indexed_time_backfill() -> None:
    """Run the repair once; never raises (except cancellation) and never blocks startup."""
    try:
        import db.engine as db_engine

        session_factory = db_engine.SessionLocal
        client = clients.opensearch
        if session_factory is None or client is None:
            return

        async with session_factory() as session:
            if await _already_done(session, MIGRATION_NAME):
                return

            stats = await _run_backfill(client, get_index_name())
            if stats is None or stats["failures"] or stats["conflicts"] or stats["deferred"]:
                logger.warning(
                    "Indexed-time backfill incomplete; will retry on next boot",
                    **(stats or {}),
                )
                return

            await _mark_done(session, MIGRATION_NAME, notes=str(stats))
            await session.commit()
            logger.info("Indexed-time backfill complete", **stats)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Indexed-time backfill failed; will retry on next boot", error=str(e))
