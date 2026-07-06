from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_index_name
from connectors.sharepoint.utils import is_valid_sharepoint_url
from dependencies import (
    get_connector_service,
    get_current_user,
    get_db_session,
    get_rbac_service,
    get_session_manager,
    has_effective_permission,
    require_permission,
)
from services.connector_access_service import (
    CONNECTOR_TYPES,
    filter_connectors_for_user,
    get_access_map,
    is_bucket_connector_type,
    is_connector_access_policy_enforced,
    is_connector_allowed_for_request,
    list_access_for_admin,
    set_connector_access_bulk,
)
from session_manager import User
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def _connector_access_denied(
    request: Request,
    session: AsyncSession,
    connector_type: str,
) -> JSONResponse | None:
    """Return 403 when workspace policy blocks this connector type."""
    if connector_type not in CONNECTOR_TYPES:
        return None
    if not is_connector_access_policy_enforced():
        return None
    if await is_connector_allowed_for_request(session, connector_type):
        return None
    return JSONResponse(
        {"error": f"Connector not available: {connector_type}"},
        status_code=403,
    )


async def _allowed_connector_types_for_request(
    request: Request,
    session: AsyncSession,
    connector_types: list[str],
) -> list[str]:
    """Drop connector types blocked by workspace policy (sync-all style endpoints)."""
    if not is_connector_access_policy_enforced():
        return connector_types
    access_map = await get_access_map(session)
    return [t for t in connector_types if access_map.get(t, True)]


def _connector_sync_should_replace(connector_type: str) -> bool:
    """Return True for connector types where sync should replace existing indexed files."""
    return connector_type in ["google_drive", "sharepoint", "onedrive"]


async def get_synced_file_ids_for_connector(
    connector_type: str,
    user_id: str,
    session_manager,
    jwt_token: str = None,
) -> tuple[list[str], list[str], str]:
    """
    Query OpenSearch for unique file IDs where connector_type matches.

    Returns a 3-tuple ``(file_ids, filenames, id_field)``:

    - ``file_ids``: connector source IDs to use for orphan detection and sync.
      Comes from the ``connector_file_id`` field when chunks were indexed via
      ``ConnectorFileProcessor`` (non-Langflow path); falls back to ``document_id``
      for Langflow-indexed chunks where ``document_id`` already holds the connector
      source ID.
    - ``filenames``: unique filenames as a fallback when ``file_ids`` is empty.
    - ``id_field``: the OpenSearch field name that ``file_ids`` came from
      (``"connector_file_id"`` or ``"document_id"``). Callers must pass this to
      ``delete_orphan_documents`` so deletions target the correct field.
    """
    try:
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)

        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": connector_type}},
            "aggs": {
                "unique_connector_file_ids": {
                    "terms": {"field": "connector_file_id", "size": 10000}
                },
                "unique_document_ids": {"terms": {"field": "document_id", "size": 10000}},
                "unique_filenames": {"terms": {"field": "filename", "size": 10000}},
            },
        }

        result = await opensearch_client.search(index=get_index_name(), body=query_body)

        # Prefer connector_file_id — these are set by ConnectorFileProcessor (non-Langflow)
        # and hold the actual connector source IDs (e.g. SharePoint GUIDs), not SHA hashes.
        connector_file_id_buckets = (
            result.get("aggregations", {}).get("unique_connector_file_ids", {}).get("buckets", [])
        )
        connector_file_ids = [b["key"] for b in connector_file_id_buckets if b["key"]]

        if connector_file_ids:
            file_ids = connector_file_ids
            id_field = "connector_file_id"
        else:
            # Langflow path: document_id already holds the connector source ID.
            doc_id_buckets = (
                result.get("aggregations", {}).get("unique_document_ids", {}).get("buckets", [])
            )
            file_ids = [b["key"] for b in doc_id_buckets if b["key"]]
            id_field = "document_id"

        filename_buckets = (
            result.get("aggregations", {}).get("unique_filenames", {}).get("buckets", [])
        )
        filenames = [b["key"] for b in filename_buckets if b["key"]]

        logger.debug(
            "Found synced files for connector",
            connector_type=connector_type,
            file_ids_count=len(file_ids),
            id_field=id_field,
            filenames_count=len(filenames),
        )

        return file_ids, filenames, id_field

    except Exception as e:
        logger.error(
            "Failed to get synced file IDs",
            connector_type=connector_type,
            error=str(e),
        )
        return [], [], "document_id"


async def get_synced_id_to_filename_map(
    connector_type: str,
    user_id: str,
    session_manager,
    jwt_token: str | None = None,
) -> dict[str, str]:
    """Return a {document_id: filename} map for files ingested under this connector_type.

    Uses a sub-aggregation so each document_id is paired with its top filename in
    a single OpenSearch round trip.
    """
    try:
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)

        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": connector_type}},
            "aggs": {
                "by_document_id": {
                    "terms": {"field": "document_id", "size": 10000},
                    "aggs": {
                        "top_filename": {"terms": {"field": "filename", "size": 1}},
                    },
                }
            },
        }

        result = await opensearch_client.search(index=get_index_name(), body=query_body)
        buckets = result.get("aggregations", {}).get("by_document_id", {}).get("buckets", [])

        mapping: dict[str, str] = {}
        for bucket in buckets:
            doc_id = bucket.get("key")
            if not doc_id:
                continue
            fn_buckets = bucket.get("top_filename", {}).get("buckets", [])
            mapping[doc_id] = fn_buckets[0]["key"] if fn_buckets else ""
        return mapping
    except Exception as e:
        logger.error(
            "Failed to build id→filename map",
            connector_type=connector_type,
            error=str(e),
        )
        return {}


async def get_synced_id_to_modified_time_map(
    connector_type: str,
    user_id: str,
    session_manager,
    jwt_token: str | None = None,
) -> dict[str, float | None]:
    """Map each ingested connector source id → its stored ``modified_time`` (epoch ms).

    Powers change detection for bucket connectors: callers compare a blob's remote
    ``modified_time`` against the stored value to decide whether a re-ingest is needed.

    A key being **present** means the source id is already ingested under this
    ``connector_type``. A value of **None** means it was ingested but no
    ``modified_time`` was persisted (pre-change-detection docs, or an ingest path that
    didn't enrich it) — callers treat that as *unchanged* to avoid a mass re-ingest.

    Keys cover both ingest layouts (mirrors ``get_synced_file_ids_for_connector``):
    the non-Langflow path stores the connector id in ``connector_file_id`` (where
    ``document_id`` is a content hash), while the Langflow path stores it in
    ``document_id``. ``connector_file_id`` wins when both are present for the same id.
    """
    try:
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)

        query_body = {
            "size": 0,
            "query": {"term": {"connector_type": connector_type}},
            "aggs": {
                "by_connector_file_id": {
                    "terms": {"field": "connector_file_id", "size": 10000},
                    "aggs": {"latest_modified": {"max": {"field": "modified_time"}}},
                },
                "by_document_id": {
                    "terms": {"field": "document_id", "size": 10000},
                    "aggs": {"latest_modified": {"max": {"field": "modified_time"}}},
                },
            },
        }

        result = await opensearch_client.search(index=get_index_name(), body=query_body)
        aggs = result.get("aggregations", {})

        mapping: dict[str, float | None] = {}
        # document_id first; connector_file_id overlays it (connector_file_id wins).
        # The content-hash document_ids from the non-Langflow path are harmless noise —
        # they never match an enumerated connector source id.
        for agg_name in ("by_document_id", "by_connector_file_id"):
            for bucket in aggs.get(agg_name, {}).get("buckets", []):
                key = bucket.get("key")
                if not key:
                    continue
                mapping[key] = bucket.get("latest_modified", {}).get("value")
        return mapping
    except Exception as e:
        logger.error(
            "Failed to build id→modified_time map",
            connector_type=connector_type,
            error=str(e),
        )
        return {}


# Tolerance (ms) to avoid a false-positive "changed" when a remote ISO timestamp
# round-trips through the OpenSearch ``date`` field with sub-second rounding.
_CHANGE_DETECTION_TOLERANCE_MS = 1000.0


def _parse_iso_to_epoch_ms(value: str | None) -> float | None:
    """Parse an ISO-8601 timestamp to epoch milliseconds, or None if unparseable."""
    if not value:
        return None
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp() * 1000.0
    except (ValueError, TypeError):
        return None


def remote_is_newer_than_synced(
    file_id: str,
    remote_modified_time: str | None,
    synced_modified_map: dict[str, float | None],
) -> bool:
    """True only when a stored ``modified_time`` exists and the remote is strictly newer.

    Missing/unparseable timestamps (remote or stored) → False, so we never re-ingest
    on ambiguity (backfill-safe).
    """
    stored_ms = synced_modified_map.get(file_id)
    if stored_ms is None:
        return False
    remote_ms = _parse_iso_to_epoch_ms(remote_modified_time)
    if remote_ms is None:
        return False
    return remote_ms - stored_ms > _CHANGE_DETECTION_TOLERANCE_MS


def classify_remote_file_change(
    file_id: str,
    remote_modified_time: str | None,
    is_ingested: bool,
    synced_modified_map: dict[str, float | None],
) -> str:
    """Classify a remote blob as ``"new"`` / ``"changed"`` / ``"unchanged"``.

    - ``new``       — not yet ingested.
    - ``changed``   — ingested and the remote version is strictly newer than stored.
    - ``unchanged`` — ingested and same-age/older, or the change can't be proven
                      (no stored token, e.g. backfill).
    """
    if not is_ingested:
        return "new"
    if remote_is_newer_than_synced(file_id, remote_modified_time, synced_modified_map):
        return "changed"
    return "unchanged"


async def bucket_changed_file_ids(
    connector,
    connector_type: str,
    user_id: str,
    session_manager,
    jwt_token: str | None,
    existing_file_ids: list[str],
) -> list[str]:
    """Return the already-ingested bucket file ids whose remote copy is newer.

    Updates-only change detection for the Sync path: list the connector's blobs
    once and keep the ids that are (a) already ingested and (b) strictly newer at
    source than the stored ``modified_time``. New blobs that aren't ingested yet
    are intentionally ignored — Sync reconciles existing files; new files are
    added via the connector's "Add from" panel. Listing exceptions propagate to
    the caller (same as the bucket_filter sync path).
    """
    existing_set = set(existing_file_ids)
    if not existing_set:
        return []

    modified_map = await get_synced_id_to_modified_time_map(
        connector_type=connector_type,
        user_id=user_id,
        session_manager=session_manager,
        jwt_token=jwt_token,
    )

    changed_ids: list[str] = []
    page_token = None
    while True:
        result = await connector.list_files(page_token=page_token)
        for f in result.get("files", []):
            fid = f.get("id")
            if not fid or fid not in existing_set:
                continue
            if (
                classify_remote_file_change(fid, f.get("modified_time"), True, modified_map)
                == "changed"
            ):
                changed_ids.append(fid)
        page_token = result.get("next_page_token")
        if not page_token:
            break

    return changed_ids


async def compute_orphans_for_connector_type(
    connector_type: str,
    user_id: str,
    connector_service,
    session_manager,
    jwt_token: str | None,
    existing_file_ids: list[str],
    id_to_filename: dict[str, str] | None = None,
) -> list[dict[str, str]] | None:
    """Compute orphan documents (ingested but no longer present at the source)
    for this connector_type without deleting them.

    Returns a list of {"document_id", "filename"} dicts. Returns None when strict
    gating aborts the pass (unauthenticated connection or listing exception) so
    callers can distinguish "no orphans" from "could not determine safely".
    """
    if not existing_file_ids:
        return []

    connections = await connector_service.connection_manager.list_connections(
        user_id=user_id, connector_type=connector_type
    )
    active = [c for c in connections if c.is_active]
    if not active:
        logger.info(
            "Skipping orphan compute — no active connections",
            connector_type=connector_type,
        )
        return None

    remote_ids: set = set()
    for conn in active:
        try:
            connector = await connector_service.get_connector(conn.connection_id)
            if not connector or not connector.is_authenticated:
                logger.info(
                    "Skipping orphan compute — connection unauthenticated",
                    connector_type=connector_type,
                    connection_id=conn.connection_id,
                )
                return None

            # Drive the per-id existence check via cfg.file_ids when the
            # connector supports it (SharePoint / OneDrive / Google Drive).
            # The flat default of list_files() only returns the *root* listing
            # (e.g. /drive/root/children for SharePoint, files-only, no folder
            # traversal), so any folder-internal file in OpenSearch would be
            # absent from remote_ids and wrongly flagged as an orphan.
            # _list_selected_files iterates each id via _get_file_metadata_by_id
            # and silently drops missing ids, so the resulting `remote_ids` is
            # exactly "the subset of existing_file_ids that still exists at
            # source" — which is what orphan detection actually needs.
            cfg = getattr(connector, "cfg", None)
            scoped_listing = cfg is not None and bool(existing_file_ids)

            original_file_ids = None
            original_folder_ids = None
            if scoped_listing:
                original_file_ids = getattr(cfg, "file_ids", None)
                original_folder_ids = getattr(cfg, "folder_ids", None)
                cfg.file_ids = list(existing_file_ids)
                cfg.folder_ids = None

            try:
                page_token = None
                while True:
                    page = await connector.list_files(page_token=page_token)
                    for f in page.get("files", []):
                        fid = f.get("id")
                        if fid:
                            remote_ids.add(fid)
                    page_token = page.get("nextPageToken") or page.get("next_page_token")
                    if not page_token:
                        break
            finally:
                if scoped_listing:
                    cfg.file_ids = original_file_ids
                    cfg.folder_ids = original_folder_ids
        except Exception as e:
            logger.warning(
                "Skipping orphan compute — listing failed",
                connector_type=connector_type,
                connection_id=conn.connection_id,
                error=str(e),
            )
            return None

    orphan_ids = [fid for fid in existing_file_ids if fid not in remote_ids]
    if not orphan_ids:
        return []

    fn_map = id_to_filename or {}
    return [{"document_id": fid, "filename": fn_map.get(fid, "")} for fid in orphan_ids]


async def delete_orphan_documents(
    orphan_ids: list[str],
    user_id: str,
    session_manager,
    jwt_token: str | None,
    id_field: str = "document_id",
) -> int:
    """Delete OpenSearch chunks for the given orphan IDs. Returns the number of
    chunks deleted (0 on failure).

    ``id_field`` must match the OpenSearch field that ``orphan_ids`` came from —
    either ``"connector_file_id"`` (ConnectorFileProcessor / non-Langflow path)
    or ``"document_id"`` (Langflow path, where document_id holds the connector
    source ID). Pass the value returned as the third element of
    ``get_synced_file_ids_for_connector()``.
    """
    if not orphan_ids:
        return 0
    from .documents import delete_chunks_by_document_ids

    try:
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)
        return await delete_chunks_by_document_ids(
            orphan_ids, opensearch_client, get_index_name(), field=id_field
        )
    except Exception as e:
        logger.error(
            "Orphan delete failed",
            orphan_count=len(orphan_ids),
            id_field=id_field,
            error=str(e),
        )
        return 0


async def reconcile_orphans_for_connector_type(
    connector_type: str,
    user_id: str,
    connector_service,
    session_manager,
    jwt_token: str | None,
    existing_file_ids: list[str],
    id_field: str = "document_id",
) -> list[str]:
    """Compute and delete orphans for a connector type. Thin wrapper around
    compute_orphans_for_connector_type + delete_orphan_documents preserved for
    callers that perform sync immediately after reconcile.

    ``id_field`` must match the OpenSearch field that ``existing_file_ids`` came
    from. Pass the value returned as the third element of
    ``get_synced_file_ids_for_connector()``.

    Returns the list of orphan file IDs that were deleted (or []).
    """
    orphans = await compute_orphans_for_connector_type(
        connector_type=connector_type,
        user_id=user_id,
        connector_service=connector_service,
        session_manager=session_manager,
        jwt_token=jwt_token,
        existing_file_ids=existing_file_ids,
    )
    if not orphans:
        return []

    orphan_ids = [o["document_id"] for o in orphans]
    deleted = await delete_orphan_documents(
        orphan_ids=orphan_ids,
        user_id=user_id,
        session_manager=session_manager,
        jwt_token=jwt_token,
        id_field=id_field,
    )
    logger.info(
        "Orphan reconcile complete",
        connector_type=connector_type,
        orphan_count=len(orphan_ids),
        deleted_chunks=deleted,
        id_field=id_field,
    )
    if deleted <= 0:
        return []
    return orphan_ids


class ConnectorSyncBody(BaseModel):
    max_files: int | None = None
    selected_files: list[Any] | None = None
    # When True, ingest ALL files from the connector (bypasses the existing-files gate).
    # Used by bucket-kind connectors on initial ingest.
    sync_all: bool = False
    # When set, only ingest files from these buckets (bucket-kind connectors).
    bucket_filter: list[str] | None = None
    # Per-request ingest options from the connector upload UI (overrides saved Knowledge for this sync).
    settings: dict[str, Any] | None = None
    # When True, files whose filename already exists in the index are replaced
    # rather than failing. Set by the provider upload UI after the user confirms
    # overwrite in the duplicate dialog.
    replace_duplicates: bool = False
    # When True (COS only), index chunks without an owner field so OpenSearch DLS
    # makes them visible to all users in the instance. Temporary CIO mechanism;
    # not a full ACL feature. Defaults to False (private).
    shared: bool = False


class ConnectorCheckDuplicatesBody(BaseModel):
    connection_id: str | None = None
    selected_files: list[Any] | None = None


def _connector_file_response(file_info: dict[str, Any], cleaned_name: str | None = None) -> dict:
    """Normalize connector file metadata into the upload page's CloudFile shape."""
    response = {
        "id": file_info.get("id"),
        "name": cleaned_name or file_info.get("name", ""),
        "mimeType": file_info.get("mimeType")
        or file_info.get("mime_type")
        or file_info.get("mimetype")
        or "",
        "isFolder": bool(file_info.get("isFolder", False)),
    }
    for source_key, target_key in (
        ("size", "size"),
        ("webUrl", "webUrl"),
        ("url", "webUrl"),
        ("webViewLink", "webViewLink"),
        ("downloadUrl", "downloadUrl"),
        ("download_url", "downloadUrl"),
    ):
        value = file_info.get(source_key)
        if value is not None and value != "":
            response[target_key] = value
    return response


async def _expand_selected_connector_files(
    connector,
    selected_files_raw: list[Any],
) -> list[dict[str, Any]]:
    file_ids = [f.get("id") for f in selected_files_raw if isinstance(f, dict) and f.get("id")]
    expanded_files_info: list[dict[str, Any]] = []

    if file_ids and hasattr(connector, "cfg"):
        original_file_ids = getattr(connector.cfg, "file_ids", None)
        original_folder_ids = getattr(connector.cfg, "folder_ids", None)
        try:
            connector.cfg.file_ids = file_ids
            connector.cfg.folder_ids = None

            result = await connector.list_files()
            for f in result.get("files", []):
                expanded_files_info.append(_connector_file_response(f))
        except Exception as e:
            logger.error("Failed to expand files in duplicate check", error=str(e))
        finally:
            connector.cfg.file_ids = original_file_ids
            connector.cfg.folder_ids = original_folder_ids

    if not expanded_files_info:
        for f in selected_files_raw:
            if isinstance(f, dict) and not f.get("isFolder"):
                expanded_files_info.append(_connector_file_response(f))

    return expanded_files_info


async def _classify_connector_duplicates(
    connector,
    selected_files_raw: list[Any],
    session_manager,
    user_id: str,
    jwt_token: str | None,
) -> dict[str, Any]:
    """Expand connector selections and split them into duplicate/non-duplicate files."""
    expanded_files_info = await _expand_selected_connector_files(connector, selected_files_raw)
    if not expanded_files_info:
        return {
            "duplicate_names": [],
            "duplicate_files": [],
            "non_duplicate_files": [],
            "duplicate_count": 0,
            "total_files": 0,
        }

    from utils.file_utils import clean_connector_filename, get_filename_aliases

    cleaned_files = []
    all_candidates = set()
    for file_info in expanded_files_info:
        cleaned_name = clean_connector_filename(file_info["name"], file_info["mimeType"])
        response_file = _connector_file_response(file_info, cleaned_name=cleaned_name)
        aliases = get_filename_aliases(cleaned_name)
        cleaned_files.append((response_file, aliases))
        all_candidates.update(aliases)

    if not all_candidates:
        return {
            "duplicate_names": [],
            "duplicate_files": [],
            "non_duplicate_files": [file_info for file_info, _ in cleaned_files],
            "duplicate_count": 0,
            "total_files": len(cleaned_files),
        }

    opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)
    query_body = {
        "size": 10000,
        "query": {"terms": {"filename": list(all_candidates)}},
        "_source": ["filename"],
    }

    existing_filenames = set()
    try:
        response = await opensearch_client.search(index=get_index_name(), body=query_body)
        hits = response.get("hits", {}).get("hits", [])
        for hit in hits:
            fn = hit.get("_source", {}).get("filename")
            if fn:
                existing_filenames.add(fn)
    except Exception as search_err:
        if "index_not_found_exception" not in str(search_err):
            raise

    duplicate_files = []
    non_duplicate_files = []
    duplicate_names = []
    for file_info, aliases in cleaned_files:
        if any(alias in existing_filenames for alias in aliases):
            duplicate_files.append(file_info)
            duplicate_names.append(file_info["name"])
        else:
            non_duplicate_files.append(file_info)

    return {
        "duplicate_names": list(dict.fromkeys(duplicate_names)),
        "duplicate_files": duplicate_files,
        "non_duplicate_files": non_duplicate_files,
        "duplicate_count": len(duplicate_files),
        "total_files": len(cleaned_files),
    }


async def connector_check_duplicates(
    connector_type: str,
    body: ConnectorCheckDuplicatesBody,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
    session: AsyncSession = Depends(get_db_session),
):
    """Check if any of the selected files or folders contain files that already exist in the index"""
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    selected_files_raw = body.selected_files
    if not selected_files_raw:
        return JSONResponse({"duplicate_names": []})

    try:
        jwt_token = user.jwt_token
        # Get all active connections for this connector type and user
        connections = await connector_service.connection_manager.list_connections(
            user_id=user.user_id, connector_type=connector_type
        )
        active_connections = [conn for conn in connections if conn.is_active]

        # If connection_id is provided, find it, otherwise find the first working connection
        working_connection = None
        if body.connection_id:
            for conn in active_connections:
                if conn.connection_id == body.connection_id:
                    working_connection = conn
                    break

        if not working_connection:
            for conn in active_connections:
                try:
                    connector = await connector_service.get_connector(conn.connection_id)
                    if connector and await connector.authenticate():
                        working_connection = conn
                        break
                except Exception:
                    continue

        if not working_connection:
            return JSONResponse(
                {"error": f"No working {connector_type} connections found"},
                status_code=404,
            )

        connector = await connector_service.get_connector(working_connection.connection_id)
        if not connector:
            return JSONResponse(
                {"error": f"Connection '{working_connection.connection_id}' not found"},
                status_code=404,
            )

        return JSONResponse(
            await _classify_connector_duplicates(
                connector=connector,
                selected_files_raw=selected_files_raw,
                session_manager=session_manager,
                user_id=user.user_id,
                jwt_token=jwt_token,
            )
        )

    except Exception:
        logger.exception("[CONNECTOR] Error checking duplicates")
        return JSONResponse({"error": "An internal error has occurred."}, status_code=500)


async def list_connectors(
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List available connector types with metadata"""
    try:
        connector_types = connector_service.connection_manager.get_available_connector_types(
            user_id=user.user_id
        )
        if is_connector_access_policy_enforced():
            access_map = await get_access_map(session)
            connector_types = filter_connectors_for_user(connector_types, access_map)
        return JSONResponse({"connectors": connector_types})
    except Exception as e:
        logger.error("[CONNECTOR] Error listing connectors", error=str(e))
        return JSONResponse({"connectors": []})


class UpdateConnectorAccessBody(BaseModel):
    access: dict[str, bool]


def _connector_access_client_error(exc: ValueError) -> str:
    """Safe client message for set_connector_access_bulk validation failures."""
    detail = str(exc)
    if detail.startswith("Unknown connector type:"):
        return "Unknown connector type"
    return "Invalid request data"


async def get_connector_workspace_policy(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Read-only stored workspace connector overrides for Connectors tab filtering.

    Returns only explicit admin saves (missing types default to allowed server-side
    but still follow deployment visibility rules on the client).
    """
    from db.repositories import WorkspaceConfigRepo
    from services.connector_access_service import CONNECTOR_ACCESS_SECTION

    stored = await WorkspaceConfigRepo(session).get_section(CONNECTOR_ACCESS_SECTION) or {}
    return JSONResponse({"access": stored})


async def get_connector_user_access(
    connector_service=Depends(get_connector_service),
    user: User = Depends(require_permission("connectors:manage:access")),
    session: AsyncSession = Depends(get_db_session),
):
    """List connector types and whether they are enabled for this workspace."""
    metadata = connector_service.connection_manager.get_available_connector_types(
        user_id=user.user_id
    )
    connectors = await list_access_for_admin(session, metadata)
    return JSONResponse({"connectors": connectors})


async def update_connector_user_access(
    body: UpdateConnectorAccessBody,
    user: User = Depends(require_permission("connectors:manage:access")),
    session: AsyncSession = Depends(get_db_session),
    connector_service=Depends(get_connector_service),
):
    """Save workspace connector availability policy."""
    try:
        await set_connector_access_bulk(
            session,
            body.access,
            user.db_user_id or user.user_id,
        )
        await session.commit()
    except ValueError as e:
        logger.error(
            "[CONNECTOR] Invalid connector access update",
            error=str(e),
        )
        return JSONResponse(
            {"error": _connector_access_client_error(e)},
            status_code=400,
        )

    metadata = connector_service.connection_manager.get_available_connector_types(
        user_id=user.user_id
    )
    connectors = await list_access_for_admin(session, metadata)
    return JSONResponse({"connectors": connectors})


async def connector_sync(
    connector_type: str,
    body: ConnectorSyncBody,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
):
    """Sync files from all active connections of a connector type"""
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    max_files = body.max_files
    selected_files_raw = body.selected_files
    selected_files = None
    file_infos = None
    if selected_files_raw:
        if isinstance(selected_files_raw[0], str):
            # Legacy format: just IDs
            selected_files = selected_files_raw
        else:
            # New format: file objects with metadata
            selected_files = [f.get("id") for f in selected_files_raw if f.get("id")]
            file_infos = selected_files_raw

    try:
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_START
        )
        logger.debug(
            "Starting connector sync",
            connector_type=connector_type,
            max_files=max_files,
        )
        jwt_token = user.jwt_token

        if body.shared and connector_type != "ibm_cos":
            return JSONResponse(
                {"error": "shared flag is only supported for the ibm_cos connector"},
                status_code=400,
            )

        # Get all active connections for this connector type and user
        connections = await connector_service.connection_manager.list_connections(
            user_id=user.user_id, connector_type=connector_type
        )

        active_connections = [conn for conn in connections if conn.is_active]
        if not active_connections:
            return JSONResponse(
                {"error": f"No active {connector_type} connections found"},
                status_code=404,
            )

        # Find the first connection that actually works
        working_connection = None
        for connection in active_connections:
            logger.debug(
                "Testing connection authentication",
                connection_id=connection.connection_id,
            )
            try:
                # Get the connector instance and test authentication
                connector = await connector_service.get_connector(connection.connection_id)
                if connector and await connector.authenticate():
                    working_connection = connection
                    logger.debug(
                        "Found working connection",
                        connection_id=connection.connection_id,
                    )
                    break
                else:
                    logger.debug(
                        "Connection authentication failed",
                        connection_id=connection.connection_id,
                    )
            except Exception as e:
                logger.debug(
                    "Connection validation failed",
                    connection_id=connection.connection_id,
                    error=str(e),
                )
                continue

        if not working_connection:
            return JSONResponse(
                {"error": f"No working {connector_type} connections found"},
                status_code=404,
            )

        # Use the working connection
        logger.debug(
            "Starting sync with working connection",
            connection_id=working_connection.connection_id,
        )

        # Branches set either ``task_id`` (single batch) or ``task_ids`` (the
        # bucket_filter path may emit two batches: new files + changed files).
        task_ids: list[str] = []

        if selected_files:
            # Explicit files selected (e.g., from file picker) - sync those specific files
            from .documents import _ensure_index_exists

            if body.shared and body.replace_duplicates:
                if not await has_effective_permission(
                    request, user, rbac, "knowledge:delete:anonymous"
                ):
                    return JSONResponse(
                        {
                            "error": "Replacing shared documents requires the knowledge:delete:anonymous permission"
                        },
                        status_code=403,
                    )

            if not body.replace_duplicates and file_infos:
                duplicate_check = await _classify_connector_duplicates(
                    connector=await connector_service.get_connector(
                        working_connection.connection_id
                    ),
                    selected_files_raw=file_infos,
                    session_manager=session_manager,
                    user_id=user.user_id,
                    jwt_token=jwt_token,
                )
                if duplicate_check["duplicate_count"] > 0:
                    file_infos = duplicate_check["non_duplicate_files"]
                    selected_files = [f["id"] for f in file_infos if f.get("id")]
                    if not selected_files:
                        return JSONResponse(
                            {
                                "status": "no_files",
                                "message": (
                                    f"All {duplicate_check['duplicate_count']} selected file(s) "
                                    "already exist. Nothing was synced."
                                ),
                                "duplicate_names": duplicate_check["duplicate_names"],
                                "duplicate_count": duplicate_check["duplicate_count"],
                                "total_files": duplicate_check["total_files"],
                            },
                            status_code=200,
                        )

            await _ensure_index_exists(jwt_token)
            task_id = await connector_service.sync_specific_files(
                working_connection.connection_id,
                user.user_id,
                selected_files,
                jwt_token=jwt_token,
                file_infos=file_infos,
                ingest_settings=body.settings,
                replace_duplicates=body.replace_duplicates,
                shared=body.shared,
            )
        elif body.sync_all or body.bucket_filter:
            # Full ingest: discover and ingest all files (or files from specific buckets).
            # Used by direct-sync providers on initial ingest or per-bucket sync.
            logger.info(
                "Full connector ingest requested",
                connector_type=connector_type,
                bucket_filter=body.bucket_filter,
            )
            connector = await connector_service.get_connector(working_connection.connection_id)
            if body.bucket_filter:
                # List only files from the requested buckets, then reconcile against
                # what's already ingested so we re-fetch only NEW and CHANGED blobs
                # (skipping unchanged ones), rather than re-downloading the whole
                # container every time. Per-file dedup in ConnectorFileProcessor is a
                # backstop, but it runs after download — this pre-filter avoids the
                # redundant fetch/reprocess and the misleading "all files" task view.
                original_buckets = connector.bucket_names
                connector.bucket_names = body.bucket_filter
                try:
                    all_files: list[dict[str, Any]] = []
                    page_token = None
                    while True:
                        result = await connector.list_files(page_token=page_token)
                        all_files.extend(result.get("files", []))
                        page_token = result.get("next_page_token")
                        if not page_token:
                            break
                finally:
                    connector.bucket_names = original_buckets

                if not all_files:
                    return JSONResponse(
                        {
                            "status": "no_files",
                            "message": "No files found in the selected buckets.",
                        },
                        status_code=200,
                    )

                # Classify each remote blob as new / changed / unchanged.
                existing_ids, _, _ = await get_synced_file_ids_for_connector(
                    connector_type=connector_type,
                    user_id=user.user_id,
                    session_manager=session_manager,
                    jwt_token=jwt_token,
                )
                existing_set = set(existing_ids)
                modified_map = await get_synced_id_to_modified_time_map(
                    connector_type=connector_type,
                    user_id=user.user_id,
                    session_manager=session_manager,
                    jwt_token=jwt_token,
                )

                new_ids: list[str] = []
                changed_ids: list[str] = []
                for f in all_files:
                    fid = f.get("id")
                    if not fid:
                        continue
                    status = classify_remote_file_change(
                        fid,
                        f.get("modified_time"),
                        fid in existing_set,
                        modified_map,
                    )
                    if status == "new":
                        new_ids.append(fid)
                    elif status == "changed":
                        changed_ids.append(fid)
                    # "unchanged" → skip; already ingested and not newer at source.

                logger.info(
                    "Reconciled bucket selection",
                    connector_type=connector_type,
                    total=len(all_files),
                    new=len(new_ids),
                    changed=len(changed_ids),
                    skipped=len(all_files) - len(new_ids) - len(changed_ids),
                )

                if not new_ids and not changed_ids:
                    return JSONResponse(
                        {
                            "status": "no_files",
                            "message": "All files in the selected buckets are already up to date.",
                        },
                        status_code=200,
                    )

                # Two batches: new files are created; changed files replace the
                # indexed copy (replace_duplicates=True bypasses the filename-skip
                # and deletes stale chunks before re-ingest). replace is batch-level,
                # hence the split.
                if new_ids:
                    task_ids.append(
                        await connector_service.sync_specific_files(
                            working_connection.connection_id,
                            user.user_id,
                            new_ids,
                            jwt_token=jwt_token,
                            ingest_settings=body.settings,
                        )
                    )
                if changed_ids:
                    task_ids.append(
                        await connector_service.sync_specific_files(
                            working_connection.connection_id,
                            user.user_id,
                            changed_ids,
                            jwt_token=jwt_token,
                            ingest_settings=body.settings,
                            replace_duplicates=True,
                        )
                    )
            else:
                # sync_all: ingest everything the connector can see
                task_id = await connector_service.sync_connector_files(
                    working_connection.connection_id,
                    user.user_id,
                    max_files=max_files,
                    jwt_token=jwt_token,
                    ingest_settings=body.settings,
                    shared=body.shared,
                )
        else:
            # No files specified - sync only files already in OpenSearch for this connector
            # This ensures deleted files stay deleted
            (
                existing_file_ids,
                existing_filenames,
                id_field,
            ) = await get_synced_file_ids_for_connector(
                connector_type=connector_type,
                user_id=user.user_id,
                session_manager=session_manager,
                jwt_token=jwt_token,
            )

            if not existing_file_ids and not existing_filenames:
                return JSONResponse(
                    {
                        "status": "no_files",
                        "message": f"No {connector_type} files to sync. Add files from the connector first.",
                    },
                    status_code=200,
                )

            # If we have connector file IDs, use sync_specific_files
            # Otherwise, use filename filtering with sync_connector_files
            if existing_file_ids:
                logger.info(
                    "Syncing specific files by connector file ID",
                    connector_type=connector_type,
                    file_count=len(existing_file_ids),
                    id_field=id_field,
                )
                # Reconcile orphans (files deleted at the source) before re-syncing.
                # Strict gating: skip when sync is capped — we'd see a partial remote
                # listing and delete legitimate files.
                ids_to_sync = list(existing_file_ids)
                if body.max_files is None:
                    orphan_ids = await reconcile_orphans_for_connector_type(
                        connector_type=connector_type,
                        user_id=user.user_id,
                        connector_service=connector_service,
                        session_manager=session_manager,
                        jwt_token=jwt_token,
                        existing_file_ids=existing_file_ids,
                        id_field=id_field,
                    )
                    if orphan_ids:
                        orphan_id_set = set(orphan_ids)
                        ids_to_sync = [fid for fid in existing_file_ids if fid not in orphan_id_set]
                if not ids_to_sync:
                    return JSONResponse(
                        {
                            "status": "no_files",
                            "message": f"Deleted stale {connector_type} files; no remaining files to sync.",
                        },
                        status_code=200,
                    )
                if is_bucket_connector_type(connector_type):
                    # Bucket Sync is updates-only: re-ingest just the blobs whose
                    # remote copy is newer than what's indexed (deleting the stale
                    # chunks via replace_duplicates). Unlike replace_duplicates=False
                    # this actually propagates content changes; unlike replacing every
                    # id it skips unchanged blobs instead of re-fetching the container.
                    connector = await connector_service.get_connector(
                        working_connection.connection_id
                    )
                    changed_ids = await bucket_changed_file_ids(
                        connector,
                        connector_type,
                        user.user_id,
                        session_manager,
                        jwt_token,
                        ids_to_sync,
                    )
                    if not changed_ids:
                        return JSONResponse(
                            {
                                "status": "no_files",
                                "message": f"All {connector_type} files are already up to date.",
                            },
                            status_code=200,
                        )
                    task_id = await connector_service.sync_specific_files(
                        working_connection.connection_id,
                        user.user_id,
                        changed_ids,
                        jwt_token=jwt_token,
                        ingest_settings=body.settings,
                        replace_duplicates=True,
                        shared=body.shared,
                    )
                else:
                    task_id = await connector_service.sync_specific_files(
                        working_connection.connection_id,
                        user.user_id,
                        ids_to_sync,
                        jwt_token=jwt_token,
                        ingest_settings=body.settings,
                        replace_duplicates=_connector_sync_should_replace(connector_type),
                        shared=body.shared,
                    )
            else:
                # Fallback: use filename filtering (for Langflow-ingested files without document_id)
                logger.info(
                    "Syncing files by filename filter (document_id not available)",
                    connector_type=connector_type,
                    filename_count=len(existing_filenames),
                )
                task_id = await connector_service.sync_connector_files(
                    working_connection.connection_id,
                    user.user_id,
                    max_files=None,
                    jwt_token=jwt_token,
                    filename_filter=set(existing_filenames),
                    ingest_settings=body.settings,
                    replace_duplicates=_connector_sync_should_replace(connector_type),
                    shared=body.shared,
                )
        # The bucket_filter path may have already populated task_ids (new + changed
        # batches); every other branch sets a single task_id.
        if not task_ids:
            task_ids = [task_id]
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_COMPLETE
        )
        return JSONResponse(
            {
                "task_ids": task_ids,
                "status": "sync_started",
                "message": f"Started syncing files from 1 {connector_type} connection",
                "connections_synced": len(task_ids),
            },
            status_code=201,
        )

    except Exception as e:
        logger.error("Connector sync failed", error=str(e))
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_FAILED
        )
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


async def connector_status(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get connector status for authenticated user"""
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    # Get connections for this connector type and user
    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type=connector_type
    )

    # Get the connector for each connection and verify authentication
    connection_details = {}
    verified_active_connections = []

    for connection in connections:
        try:
            connector = await connector_service._get_connector(connection.connection_id)
            if connector is not None:
                # Actually verify the connection by trying to authenticate
                is_authenticated = await connector.authenticate()

                # Get base URL if available (for SharePoint/OneDrive connectors)
                base_url = None
                if hasattr(connector, "base_url"):
                    base_url = connector.base_url
                    logger.debug(
                        f"connector_status: Got base_url from connector.base_url: {base_url}"
                    )
                elif hasattr(connector, "sharepoint_url"):
                    base_url = connector.sharepoint_url  # Backward compatibility
                    logger.debug(
                        f"connector_status: Got base_url from connector.sharepoint_url: {base_url}"
                    )
                else:
                    logger.debug(
                        "connector_status: Connector has no base_url or sharepoint_url attribute"
                    )

                connection_details[connection.connection_id] = {
                    "client_id": connector.get_client_id(),
                    "is_authenticated": is_authenticated,
                    "base_url": base_url,
                }
                if is_authenticated and connection.is_active:
                    verified_active_connections.append(connection)
            else:
                connection_details[connection.connection_id] = {
                    "client_id": None,
                    "is_authenticated": False,
                    "base_url": None,
                }
        except Exception as e:
            logger.warning(
                "Could not verify connector authentication",
                connection_id=connection.connection_id,
                error=str(e),
            )
            connection_details[connection.connection_id] = {
                "client_id": None,
                "is_authenticated": False,
                "base_url": None,
            }

    # Only count connections that are both active AND actually authenticated
    has_authenticated_connection = len(verified_active_connections) > 0

    return JSONResponse(
        {
            "connector_type": connector_type,
            "authenticated": has_authenticated_connection,
            "status": "connected" if has_authenticated_connection else "not_connected",
            "connections": [
                {
                    "connection_id": conn.connection_id,
                    "name": conn.name,
                    "client_id": connection_details.get(conn.connection_id, {}).get("client_id"),
                    "is_active": conn.is_active
                    and connection_details.get(conn.connection_id, {}).get(
                        "is_authenticated", False
                    ),
                    "is_authenticated": connection_details.get(conn.connection_id, {}).get(
                        "is_authenticated", False
                    ),
                    "base_url": connection_details.get(conn.connection_id, {}).get("base_url"),
                    "created_at": conn.created_at.isoformat(),
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                }
                for conn in connections
            ],
        }
    )


# Drive watches registered with a legacy webhook URL may point at
# /connectors/google/webhook; accept them until those channels expire.
LEGACY_WEBHOOK_TYPE_ALIASES = {"google": "google_drive"}


async def connector_webhook(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    session: AsyncSession = Depends(get_db_session),
):
    """Handle webhook notifications from any connector type"""

    canonical_type = LEGACY_WEBHOOK_TYPE_ALIASES.get(connector_type)
    if canonical_type:
        logger.warning(
            "Legacy webhook connector type received, aliasing",
            received=connector_type,
            canonical=canonical_type,
        )
        connector_type = canonical_type

    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    # Handle webhook validation (connector-specific)
    temp_config = {"token_file": "temp.json"}
    from connectors.connection_manager import ConnectionConfig

    temp_connection = ConnectionConfig(
        connection_id="temp",
        connector_type=str(connector_type),
        name="temp",
        config=temp_config,
    )
    try:
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_WEBHOOK_RECV
        )
        temp_connector = connector_service.connection_manager._create_connector(temp_connection)
        validation_response = temp_connector.handle_webhook_validation(
            request.method, dict(request.headers), dict(request.query_params)
        )
        if validation_response:
            return PlainTextResponse(validation_response)
    except (NotImplementedError, ValueError):
        # Connector type not found or validation not needed
        pass

    try:
        # Get the raw payload and headers
        payload = {}
        headers = dict(request.headers)

        if request.method == "POST":
            content_type = headers.get("content-type", "").lower()
            if "application/json" in content_type:
                payload = await request.json()
            else:
                # Some webhooks send form data or plain text
                body = await request.body()
                payload = {"raw_body": body.decode("utf-8") if body else ""}
        else:
            # GET webhooks use query params
            payload = dict(request.query_params)

        # Add headers to payload for connector processing
        payload["_headers"] = headers
        payload["_method"] = request.method

        logger.info("Webhook notification received", connector_type=connector_type)

        # Extract channel/subscription ID using connector-specific method
        try:
            temp_connector = connector_service.connection_manager._create_connector(temp_connection)
            channel_id = temp_connector.extract_webhook_channel_id(payload, headers)
        except (NotImplementedError, ValueError):
            channel_id = None

        if not channel_id:
            logger.warning("No channel ID found in webhook", connector_type=connector_type)
            return JSONResponse({"status": "ignored", "reason": "no_channel_id"})

        # Find the specific connection for this webhook
        connection = await connector_service.connection_manager.get_connection_by_webhook_id(
            channel_id
        )
        if not connection or not connection.is_active:
            logger.info("Unknown webhook channel, will auto-expire", channel_id=channel_id)
            return JSONResponse({"status": "ignored_unknown_channel", "channel_id": channel_id})

        # Process webhook for the specific connection
        try:
            # Get the connector instance
            connector = await connector_service._get_connector(connection.connection_id)
            if not connector:
                logger.error(
                    "Could not get connector for connection",
                    connection_id=connection.connection_id,
                )
                return JSONResponse({"status": "error", "reason": "connector_not_found"})

            # Let the connector handle the webhook and return affected file IDs
            affected_files = await connector.handle_webhook(payload)

            user = session_manager.get_user(connection.user_id)
            jwt_token = user.jwt_token if user else None

            # Scope guard: a connection's picker selection is not persisted, so
            # the connector can't filter the change feed to it. Restrict webhook
            # ingestion to files ALREADY indexed for this connector — the same
            # durable scope the no-selection manual sync uses. This stops a stray
            # change (even just opening a file) from auto-ingesting a file the
            # user never selected. Deletions of indexed files still pass (they
            # remain in the index until cleaned up) so chunk-cleanup runs.
            in_scope: list[str] = []
            if affected_files:
                indexed_ids, _filenames, _id_field = await get_synced_file_ids_for_connector(
                    connector_type=connector_type,
                    user_id=connection.user_id,
                    session_manager=session_manager,
                    jwt_token=jwt_token,
                )
                indexed_set = set(indexed_ids)
                in_scope = [f for f in affected_files if f in indexed_set]

            if in_scope:
                logger.info(
                    "Webhook connection files affected",
                    connection_id=connection.connection_id,
                    affected_count=len(affected_files),
                    in_scope_count=len(in_scope),
                )

                # Trigger incremental sync for affected files. The webhook fires
                # because the file changed, so replace the indexed copy instead of
                # tripping the duplicate-filename guard meant for manual uploads.
                task_id = await connector_service.sync_specific_files(
                    connection.connection_id,
                    connection.user_id,
                    in_scope,
                    jwt_token=jwt_token,
                    replace_duplicates=_connector_sync_should_replace(connector_type),
                )

                result = {
                    "connection_id": connection.connection_id,
                    "task_id": task_id,
                    "affected_files": len(in_scope),
                }
            elif affected_files:
                # Changes detected, but none are within the indexed scope —
                # ignore so unselected files are not auto-ingested.
                logger.info(
                    "Webhook changes outside synced scope, ignored",
                    connection_id=connection.connection_id,
                    affected_count=len(affected_files),
                    in_scope_count=0,
                )

                result = {
                    "connection_id": connection.connection_id,
                    "action": "ignored",
                    "reason": "out_of_scope",
                }
            else:
                # No specific files identified - just log the webhook
                logger.info(
                    "Webhook general change detected, no specific files",
                    connection_id=connection.connection_id,
                )

                result = {
                    "connection_id": connection.connection_id,
                    "action": "logged_only",
                    "reason": "no_specific_files",
                }

            return JSONResponse(
                {
                    "status": "processed",
                    "connector_type": connector_type,
                    "channel_id": channel_id,
                    **result,
                }
            )

        except Exception as e:
            logger.exception(
                "[CONNECTOR] Failed to process webhook",
                connection_id=connection.connection_id,
            )
            return JSONResponse(
                {
                    "status": "error",
                    "connector_type": connector_type,
                    "channel_id": channel_id,
                    "error": str(e),
                },
                status_code=500,
            )

    except Exception as e:
        logger.error("Webhook processing failed", error=str(e))
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_WEBHOOK_FAILED
        )
        return JSONResponse({"error": f"Webhook processing failed: {str(e)}"}, status_code=500)


async def connector_disconnect(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(require_permission("connectors:delete:own")),
    session: AsyncSession = Depends(get_db_session),
):
    """Disconnect a connector by deleting its connection"""
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    try:
        # Get connections for this connector type and user
        connections = await connector_service.connection_manager.list_connections(
            user_id=user.user_id, connector_type=connector_type
        )

        if not connections:
            return JSONResponse(
                {"error": f"No {connector_type} connections found"},
                status_code=404,
            )

        # Delete all connections for this connector type and user
        deleted_count = 0
        for connection in connections:
            try:
                # Get the connector to cleanup any subscriptions
                connector = await connector_service._get_connector(connection.connection_id)
                if connector and hasattr(connector, "cleanup_subscription"):
                    subscription_id = connection.config.get("webhook_channel_id")
                    if subscription_id:
                        try:
                            await connector.cleanup_subscription(subscription_id)
                        except Exception as e:
                            logger.warning(
                                "Failed to cleanup subscription",
                                connection_id=connection.connection_id,
                                error=str(e),
                            )
            except Exception as e:
                logger.warning(
                    "Could not get connector for cleanup",
                    connection_id=connection.connection_id,
                    error=str(e),
                )

            # Delete the connection
            success = await connector_service.connection_manager.delete_connection(
                connection.connection_id
            )
            if success:
                deleted_count += 1

        logger.info(
            "Disconnected connector",
            connector_type=connector_type,
            user_id=user.user_id,
            deleted_count=deleted_count,
        )

        return JSONResponse(
            {
                "status": "disconnected",
                "connector_type": connector_type,
                "deleted_connections": deleted_count,
            }
        )

    except Exception as e:
        logger.error(
            "Failed to disconnect connector",
            connector_type=connector_type,
            error=str(e),
        )
        return JSONResponse(
            {"error": f"Disconnect failed: {str(e)}"},
            status_code=500,
        )


# ---------------------------------------------------------------------------


async def sync_all_connectors(
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Sync files from all active cloud connector connections.
    """
    try:
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_START
        )
        jwt_token = user.jwt_token

        all_task_ids = []
        synced_connectors = []
        skipped_connectors = []
        deleted_only_connectors = []
        errors = []

        connector_types = await _allowed_connector_types_for_request(
            request, session, _cloud_connector_types()
        )
        for connector_type in connector_types:
            try:
                # First, get existing file IDs/filenames from OpenSearch for this connector type
                (
                    existing_file_ids,
                    existing_filenames,
                    id_field,
                ) = await get_synced_file_ids_for_connector(
                    connector_type=connector_type,
                    user_id=user.user_id,
                    session_manager=session_manager,
                    jwt_token=jwt_token,
                )

                if not existing_file_ids and not existing_filenames:
                    logger.debug(
                        "No existing files in OpenSearch for connector type, skipping",
                        connector_type=connector_type,
                    )
                    skipped_connectors.append(connector_type)
                    continue

                # Get all active connections for this connector type and user
                connections = await connector_service.connection_manager.list_connections(
                    user_id=user.user_id, connector_type=connector_type
                )

                active_connections = [conn for conn in connections if conn.is_active]
                if not active_connections:
                    logger.debug(
                        "No active connections for connector type",
                        connector_type=connector_type,
                    )
                    continue

                # Find the first connection that actually works
                working_connection = None
                for connection in active_connections:
                    try:
                        connector = await connector_service.get_connector(connection.connection_id)
                        if connector and await connector.authenticate():
                            working_connection = connection
                            break
                    except Exception as e:
                        logger.debug(
                            "Connection validation failed",
                            connection_id=connection.connection_id,
                            error=str(e),
                        )
                        continue

                if not working_connection:
                    logger.debug(
                        "No working connection for connector type",
                        connector_type=connector_type,
                    )
                    continue

                # Sync using connector file IDs if available, else use filename filter
                if existing_file_ids:
                    logger.info(
                        "Syncing specific files by connector file ID",
                        connector_type=connector_type,
                        file_count=len(existing_file_ids),
                        id_field=id_field,
                    )
                    # Reconcile orphans (files deleted at the source) before re-syncing.
                    # sync_all_connectors has no caps or filters, so gating reduces
                    # to the strict checks inside the helper.
                    orphan_ids = await reconcile_orphans_for_connector_type(
                        connector_type=connector_type,
                        user_id=user.user_id,
                        connector_service=connector_service,
                        session_manager=session_manager,
                        jwt_token=jwt_token,
                        existing_file_ids=existing_file_ids,
                        id_field=id_field,
                    )
                    if orphan_ids:
                        orphan_id_set = set(orphan_ids)
                        existing_file_ids = [
                            fid for fid in existing_file_ids if fid not in orphan_id_set
                        ]
                    if not existing_file_ids:
                        deleted_only_connectors.append(connector_type)
                        continue
                    if is_bucket_connector_type(connector_type):
                        # Updates-only change detection (see connector_sync): re-ingest
                        # only blobs that changed at source, replacing stale chunks.
                        connector = await connector_service.get_connector(
                            working_connection.connection_id
                        )
                        changed_ids = await bucket_changed_file_ids(
                            connector,
                            connector_type,
                            user.user_id,
                            session_manager,
                            jwt_token,
                            existing_file_ids,
                        )
                        if not changed_ids:
                            # Nothing changed at source — already up to date.
                            skipped_connectors.append(connector_type)
                            continue
                        task_id = await connector_service.sync_specific_files(
                            working_connection.connection_id,
                            user.user_id,
                            changed_ids,
                            jwt_token=jwt_token,
                            replace_duplicates=True,
                        )
                    else:
                        task_id = await connector_service.sync_specific_files(
                            working_connection.connection_id,
                            user.user_id,
                            existing_file_ids,
                            jwt_token=jwt_token,
                            replace_duplicates=_connector_sync_should_replace(connector_type),
                        )
                else:
                    # Fallback: use filename filtering
                    logger.info(
                        "Syncing files by filename filter",
                        connector_type=connector_type,
                        filename_count=len(existing_filenames),
                    )
                    task_id = await connector_service.sync_connector_files(
                        working_connection.connection_id,
                        user.user_id,
                        max_files=None,
                        jwt_token=jwt_token,
                        filename_filter=set(existing_filenames),
                        replace_duplicates=_connector_sync_should_replace(connector_type),
                    )

                all_task_ids.append(task_id)
                synced_connectors.append(connector_type)
                logger.info(
                    "Started sync for connector type",
                    connector_type=connector_type,
                    task_id=task_id,
                    file_count=len(existing_file_ids)
                    if existing_file_ids
                    else len(existing_filenames),
                )

            except Exception as e:
                logger.error(
                    "Failed to sync connector type",
                    connector_type=connector_type,
                    error=str(e),
                )
                errors.append({"connector_type": connector_type, "error": str(e)})

        if not all_task_ids and not errors:
            if deleted_only_connectors:
                return JSONResponse(
                    {
                        "status": "no_files",
                        "message": "Deleted stale cloud files; no remaining files to sync.",
                        "skipped_connectors": skipped_connectors if skipped_connectors else None,
                        "deleted_only_connectors": deleted_only_connectors,
                    },
                    status_code=200,
                )
            if skipped_connectors:
                return JSONResponse(
                    {
                        "status": "no_files",
                        "message": "No files to sync. Add files from cloud connectors first.",
                        "skipped_connectors": skipped_connectors,
                    },
                    status_code=200,
                )
            return JSONResponse(
                {"error": "No active cloud connector connections found"},
                status_code=404,
            )

        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_COMPLETE
        )
        return JSONResponse(
            {
                "task_ids": all_task_ids,
                "status": "sync_started",
                "message": f"Started syncing files from {len(synced_connectors)} cloud connector(s)",
                "synced_connectors": synced_connectors,
                "skipped_connectors": skipped_connectors if skipped_connectors else None,
                "errors": errors if errors else None,
            },
            status_code=201,
        )

    except Exception as e:
        logger.error("Sync all connectors failed", error=str(e))
        await TelemetryClient.send_event(
            Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_FAILED
        )
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


def _cloud_connector_types() -> list[str]:
    from connectors.registry import get_connector_classes

    return [cls.CONNECTOR_TYPE for cls in get_connector_classes()]


async def _preview_orphans_for_connector_type(
    connector_type: str,
    user_id: str,
    connector_service,
    session_manager,
    jwt_token: str | None,
) -> tuple[list[dict[str, str]] | None, int]:
    """Helper: compute orphans (no deletion) + return total synced count.

    Returns (orphans, synced_count). `orphans` is None when strict gating aborts
    (so the caller can surface a "couldn't determine" state); [] when no orphans.
    """
    existing_file_ids, existing_filenames, _ = await get_synced_file_ids_for_connector(
        connector_type=connector_type,
        user_id=user_id,
        session_manager=session_manager,
        jwt_token=jwt_token,
    )

    synced_count = len(existing_file_ids) if existing_file_ids else len(existing_filenames)
    if not existing_file_ids:
        # No document_ids to diff against (e.g. Langflow-only ingest). Filename-only
        # fallback can't detect orphans safely — surface empty list.
        return [], synced_count

    id_to_filename = await get_synced_id_to_filename_map(
        connector_type=connector_type,
        user_id=user_id,
        session_manager=session_manager,
        jwt_token=jwt_token,
    )

    orphans = await compute_orphans_for_connector_type(
        connector_type=connector_type,
        user_id=user_id,
        connector_service=connector_service,
        session_manager=session_manager,
        jwt_token=jwt_token,
        existing_file_ids=existing_file_ids,
        id_to_filename=id_to_filename,
    )
    if orphans is not None:
        synced_count = max(0, synced_count - len(orphans))
    return orphans, synced_count


async def connector_sync_preview(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
    session: AsyncSession = Depends(get_db_session),
):
    """Preview the impact of syncing a connector type without performing any
    deletion or ingest. Returns the list of orphan files (present in OpenSearch
    but no longer at the source) by filename, plus the total synced count.
    """
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    try:
        orphans, synced_count = await _preview_orphans_for_connector_type(
            connector_type=connector_type,
            user_id=user.user_id,
            connector_service=connector_service,
            session_manager=session_manager,
            jwt_token=user.jwt_token,
        )
        return JSONResponse(
            {
                "connector_type": connector_type,
                "synced_count": synced_count,
                "orphans": orphans or [],
                "orphans_available": orphans is not None,
            },
            status_code=200,
        )
    except Exception as e:
        logger.error("Sync preview failed", connector_type=connector_type, error=str(e))
        return JSONResponse({"error": f"Sync preview failed: {str(e)}"}, status_code=500)


async def connectors_sync_all_preview(
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
    session: AsyncSession = Depends(get_db_session),
):
    """Preview the impact of sync-all-connectors across every cloud connector
    type. Returns orphan filenames grouped by connector_type plus a per-type
    synced count.
    """
    try:
        orphans_by_type: dict[str, list[dict[str, str]]] = {}
        synced_count_by_type: dict[str, int] = {}
        orphans_available_by_type: dict[str, bool] = {}

        connector_types = await _allowed_connector_types_for_request(
            request, session, _cloud_connector_types()
        )
        for connector_type in connector_types:
            try:
                orphans, synced_count = await _preview_orphans_for_connector_type(
                    connector_type=connector_type,
                    user_id=user.user_id,
                    connector_service=connector_service,
                    session_manager=session_manager,
                    jwt_token=user.jwt_token,
                )
            except Exception as e:
                logger.warning(
                    "Sync-all preview: per-connector failure",
                    connector_type=connector_type,
                    error=str(e),
                )
                orphans, synced_count = None, 0

            # Only include connector types that have something synced.
            if synced_count == 0 and not orphans:
                continue

            synced_count_by_type[connector_type] = synced_count
            orphans_by_type[connector_type] = orphans or []
            orphans_available_by_type[connector_type] = orphans is not None

        return JSONResponse(
            {
                "orphans_by_type": orphans_by_type,
                "synced_count_by_type": synced_count_by_type,
                "orphans_available_by_type": orphans_available_by_type,
            },
            status_code=200,
        )
    except Exception as e:
        logger.error("Sync-all preview failed", error=str(e))
        return JSONResponse({"error": f"Sync-all preview failed: {str(e)}"}, status_code=500)


async def connector_token(
    connector_type: str,
    connection_id: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get access token for connector API calls (e.g., Pickers)."""
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    url_connector_type = connector_type

    try:
        # 1) Load the connection and verify ownership
        connection = await connector_service.connection_manager.get_connection(connection_id)
        if not connection or connection.user_id != user.user_id:
            return JSONResponse({"error": "Connection not found"}, status_code=404)

        # 2) Get the ACTUAL connector instance/type for this connection_id
        connector = await connector_service._get_connector(connection_id)
        if not connector:
            return JSONResponse(
                {
                    "error": f"Connector not available - authentication may have failed for {url_connector_type}"
                },
                status_code=404,
            )

        real_type = getattr(connector, "type", None) or getattr(connection, "connector_type", None)
        if real_type is None:
            return JSONResponse({"error": "Unable to determine connector type"}, status_code=500)

        # Optional: warn if URL path type disagrees with real type
        if url_connector_type and url_connector_type != real_type:
            # You can downgrade this to debug if you expect cross-routing.
            return JSONResponse(
                {
                    "error": "Connector type mismatch",
                    "detail": {
                        "requested_type": url_connector_type,
                        "actual_type": real_type,
                        "hint": "Call the token endpoint using the correct connector_type for this connection_id.",
                    },
                },
                status_code=400,
            )

        # 3) Branch by the actual connector type
        # GOOGLE DRIVE (google-auth)
        if real_type == "google_drive" and hasattr(connector, "oauth"):
            await connector.oauth.load_credentials()
            if connector.oauth.creds and connector.oauth.creds.valid:
                expires_in = None
                try:
                    if connector.oauth.creds.expiry:
                        import time

                        expires_in = max(
                            0, int(connector.oauth.creds.expiry.timestamp() - time.time())
                        )
                except Exception:
                    expires_in = None

                return JSONResponse(
                    {
                        "access_token": connector.oauth.creds.token,
                        "expires_in": expires_in,
                    }
                )
            return JSONResponse({"error": "Invalid or expired credentials"}, status_code=401)

        # ONEDRIVE / SHAREPOINT (MSAL or custom)
        if real_type in ("onedrive", "sharepoint") and hasattr(connector, "oauth"):
            # Ensure cache/credentials are loaded before trying to use them
            try:
                # Prefer a dedicated is_authenticated() that loads cache internally
                if hasattr(connector.oauth, "is_authenticated"):
                    ok = await connector.oauth.is_authenticated()
                else:
                    # Fallback: try to load credentials explicitly if available
                    ok = True
                    if hasattr(connector.oauth, "load_credentials"):
                        ok = await connector.oauth.load_credentials()

                if not ok:
                    return JSONResponse({"error": "Not authenticated"}, status_code=401)

                # Check if a specific resource is requested (for SharePoint File Picker v8)
                # The File Picker requires a token with SharePoint as the audience, not Graph
                resource = request.query_params.get("resource")

                if resource and is_valid_sharepoint_url(resource):
                    # SharePoint File Picker v8 needs a SharePoint-scoped token
                    logger.info(f"Acquiring SharePoint-scoped token for resource: {resource}")
                    if hasattr(connector.oauth, "get_access_token_for_resource"):
                        access_token = connector.oauth.get_access_token_for_resource(resource)
                    else:
                        # Fallback for connectors without resource-specific token support
                        access_token = connector.oauth.get_access_token()
                else:
                    # Default: Microsoft Graph token
                    access_token = connector.oauth.get_access_token()
                # MSAL result has expiry, but we’re returning a raw token; keep expires_in None for simplicity
                return JSONResponse({"access_token": access_token, "expires_in": None})
            except ValueError as e:
                # Typical when acquire_token_silent fails (e.g., needs re-auth)
                return JSONResponse(
                    {"error": f"Failed to get access token: {str(e)}"}, status_code=401
                )
            except Exception as e:
                return JSONResponse({"error": f"Authentication error: {str(e)}"}, status_code=500)

        return JSONResponse(
            {"error": "Token not available for this connector type"}, status_code=400
        )

    except Exception as e:
        logger.error("Error getting connector token", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def browse_connection_files(
    connector_type: str,
    connection_id: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    bucket: str | None = None,
    search: str | None = None,
    page_token: str | None = None,
    max_files: int = 100,
):
    """
    Browse remote files in a connector with ingestion status.

    Lists files from the remote source (e.g., S3 bucket) and marks each
    as ingested or not by cross-referencing with OpenSearch.
    """
    if denied := await _connector_access_denied(request, session, connector_type):
        return denied

    try:
        connector = await connector_service.get_connector(connection_id)
        if not connector:
            return JSONResponse(
                {"error": "Connection not found or connector unavailable"},
                status_code=404,
            )

        if not await connector.authenticate():
            return JSONResponse(
                {"error": "Connector authentication failed"},
                status_code=401,
            )

        # Temporarily override bucket filter if specified
        original_buckets = None
        if bucket and hasattr(connector, "bucket_names"):
            original_buckets = connector.bucket_names
            connector.bucket_names = [bucket]

        try:
            files_result = await connector.list_files(page_token=page_token, max_files=max_files)
        finally:
            if original_buckets is not None:
                connector.bucket_names = original_buckets

        remote_files = files_result.get("files", [])
        next_page_token = files_result.get("next_page_token")

        # Filter by filename search if provided
        if search:
            search_lower = search.lower()
            remote_files = [f for f in remote_files if search_lower in f.get("name", "").lower()]

        # Get already-ingested file IDs from OpenSearch
        ingested_ids, ingested_filenames, _ = await get_synced_file_ids_for_connector(
            connector_type=connector_type,
            user_id=user.user_id,
            session_manager=session_manager,
            jwt_token=user.jwt_token,
        )
        ingested_set = set(ingested_ids) | set(ingested_filenames)

        # Stored modified_time per ingested source id, for "update available" detection.
        modified_map = await get_synced_id_to_modified_time_map(
            connector_type=connector_type,
            user_id=user.user_id,
            session_manager=session_manager,
            jwt_token=user.jwt_token,
        )

        # Merge ingestion status into remote file list
        enriched_files = []
        for f in remote_files:
            file_id = f.get("id", "")
            is_ingested = file_id in ingested_set or f.get("name", "") in ingested_set
            # "Update available": ingested, but the source version is newer than what
            # we indexed. The frontend keeps unchanged files disabled but lets the user
            # re-ingest stale ones (with replace_duplicates).
            is_stale = is_ingested and remote_is_newer_than_synced(
                file_id, f.get("modified_time"), modified_map
            )
            enriched_files.append(
                {
                    "id": file_id,
                    "name": f.get("name", ""),
                    "bucket": f.get("bucket", ""),
                    "key": f.get("key", ""),
                    "size": f.get("size", 0),
                    "modified_time": f.get("modified_time", ""),
                    "is_ingested": is_ingested,
                    "is_stale": is_stale,
                }
            )

        return JSONResponse(
            {
                "files": enriched_files,
                "next_page_token": next_page_token,
                "total_remote": len(enriched_files),
                "total_ingested": sum(1 for f in enriched_files if f["is_ingested"]),
            }
        )

    except Exception as e:
        logger.error(
            "Failed to browse connection files",
            connector_type=connector_type,
            connection_id=connection_id,
            error=str(e),
        )
        return JSONResponse(
            {"error": f"Failed to browse files: {str(e)}"},
            status_code=500,
        )
