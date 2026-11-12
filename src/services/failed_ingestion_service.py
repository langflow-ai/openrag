"""Bookkeeping for connector files that failed to ingest.

Thin, failure-tolerant wrappers around :class:`FailedIngestionRepo`. Ingestion
must never break because the registry is unavailable, so every write helper
logs and swallows its own errors; callers on the read path treat "unavailable"
as "nothing is blocked".
"""

from collections.abc import Iterable

from db.models import FailedIngestion
from db.repositories.failed_ingestion_repo import FailedIngestionRepo, max_attempts
from utils.logging_config import get_logger

logger = get_logger(__name__)

# (content_etag, modified_time) of a file as reported by the source listing.
FileVersion = tuple[str | None, str | None]


def _session_factory():
    from db import engine as db_engine

    if db_engine.SessionLocal is None:
        db_engine.init_engine()
    return db_engine.SessionLocal


def is_blocked(row: FailedIngestion, etag: str | None, modified_time: str | None) -> bool:
    """Whether a registry entry should keep this file out of the next run.

    Blocked only once the retry budget is spent AND the source version is the
    one that failed. A file changed at the source (new etag or modified time)
    is never blocked, so fixing a document and re-uploading it needs no manual
    step.
    """
    return (
        row.attempt_count >= max_attempts()
        and row.content_etag == etag
        and row.modified_time == modified_time
    )


async def record_failure(
    user_id: str,
    connector_type: str,
    file_id: str,
    error: str | None,
    filename: str | None = None,
    version: FileVersion | None = None,
) -> None:
    etag, modified_time = version or (None, None)
    try:
        async with _session_factory()() as session:
            await FailedIngestionRepo(session).record_failure(
                user_id,
                connector_type,
                file_id,
                error,
                filename=filename,
                content_etag=etag,
                modified_time=modified_time,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record failed ingestion", file_id=file_id, error=str(exc))


async def clear_failure(user_id: str, connector_type: str, file_id: str) -> None:
    """Forget a file after it ingests successfully."""
    try:
        async with _session_factory()() as session:
            if await FailedIngestionRepo(session).clear(user_id, connector_type, file_id):
                await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not clear failed ingestion", file_id=file_id, error=str(exc))


async def blocked_file_ids(
    user_id: str,
    connector_type: str,
    listed_files: Iterable[dict],
) -> dict[str, FailedIngestion]:
    """Return the listed files that must be skipped, keyed by file id."""
    try:
        async with _session_factory()() as session:
            rows = await FailedIngestionRepo(session).list_for_user(user_id, connector_type)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read failed-ingestion registry", error=str(exc))
        return {}

    by_id = {row.file_id: row for row in rows}
    blocked: dict[str, FailedIngestion] = {}
    for f in listed_files:
        row = by_id.get(f.get("id"))
        if row is not None and is_blocked(row, f.get("etag"), f.get("modified_time")):
            blocked[row.file_id] = row
    return blocked
