from fastapi import Depends
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger

from dependencies import get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


async def _sync_knowledge_filters_after_rename(
    session_manager,
    user_id: str,
    jwt_token: str | None,
    old_filename: str,
    new_filename: str,
    document_id: str | None,
) -> tuple[bool, str | None]:
    """Patch saved knowledge filters (refs + selection keys) after a successful rename."""
    from services.knowledge_filter_service import KnowledgeFilterService

    try:
        svc = KnowledgeFilterService(session_manager)
        sync_result = await svc.sync_filters_after_document_rename(
            old_filename=old_filename,
            new_filename=new_filename,
            document_id=document_id,
            user_id=user_id,
            jwt_token=jwt_token,
        )
        if not sync_result.get("success", False):
            error_msg = (
                "Could not sync knowledge filters after document rename: "
                f"{sync_result.get('error', 'unknown error')}"
            )
            logger.warning(error_msg, user_id=user_id, document_id=document_id)
            return False, error_msg
        return True, None
    except Exception as sync_err:
        logger.exception(
            "Could not sync knowledge filters after document rename",
            user_id=user_id,
            document_id=document_id,
            error=str(sync_err),
        )
        error_msg = "Could not sync knowledge filters after document rename"
        return False, error_msg


class DeleteDocumentBody(BaseModel):
    filename: str


class RenameDocumentBody(BaseModel):
    current_filename: str
    new_filename: str
    document_id: str | None = Field(default=None)


async def delete_documents_by_filename_core(
    filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
):
    """Shared delete-by-filename logic for v1 and non-v1 endpoints."""
    from config.settings import get_index_name
    from utils.opensearch_queries import build_filename_delete_body

    normalized_filename = (filename or "").strip()
    if not normalized_filename:
        return (
            {
                "success": False,
                "deleted_chunks": 0,
                "filename": normalized_filename,
                "message": None,
                "error": "Filename is required",
            },
            400,
        )

    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )
        delete_query = build_filename_delete_body(normalized_filename)
        result = await opensearch_client.delete_by_query(
            index=get_index_name(),
            body=delete_query,
            conflicts="proceed",
        )

        deleted_count = result.get("deleted", 0)
        logger.info(
            f"Deleted {deleted_count} chunks for filename {normalized_filename}",
            user_id=user_id,
        )

        if deleted_count == 0:
            return (
                {
                    "success": False,
                    "deleted_chunks": 0,
                    "filename": normalized_filename,
                    "message": None,
                    "error": "No matching document chunks were deleted. The file may be missing or not deletable in the current user context.",
                },
                404,
            )

        return (
            {
                "success": True,
                "deleted_chunks": deleted_count,
                "filename": normalized_filename,
                "message": f"All documents with filename '{normalized_filename}' deleted successfully",
                "error": None,
            },
            200,
        )
    except Exception as e:
        logger.error(
            "Error deleting documents by filename",
            filename=normalized_filename,
            error=str(e),
        )
        error_str = str(e)
        status_code = 403 if "AuthenticationException" in error_str else 500
        return (
            {
                "success": False,
                "deleted_chunks": 0,
                "filename": normalized_filename,
                "message": None,
                "error": (
                    "Access denied: insufficient permissions"
                    if status_code == 403
                    else "An internal error has occurred while deleting documents"
                ),
            },
            status_code,
        )


def _hits_total_value(resp: dict) -> int:
    total = resp.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value", 0))
    return int(total or 0)


async def _count_chunks_for_query(
    opensearch_client, index_name: str, query: dict
) -> int:
    resp = await opensearch_client.search(
        index=index_name,
        body={"query": query, "size": 0, "track_total_hits": True},
    )
    return _hits_total_value(resp)


async def _sample_document_id_from_query(
    opensearch_client,
    index_name: str,
    query: dict,
    sample_size: int = 100,
) -> str | None:
    """Return a non-empty document_id from sample hits, or None."""
    resp = await opensearch_client.search(
        index=index_name,
        body={
            "query": query,
            "size": sample_size,
            "_source": ["document_id"],
            "track_total_hits": True,
        },
    )
    for h in resp.get("hits", {}).get("hits", []):
        src = h.get("_source") or {}
        did = src.get("document_id")
        if did is not None and str(did).strip():
            return str(did).strip()
    return None


async def _rename_target_filename_taken(
    opensearch_client,
    index_name: str,
    owner_user_id: str,
    new_filename: str,
    exclude_document_id: str | None,
    jwt_token: str | None,
) -> bool:
    """True if another document (same owner) already uses this filename or an alias."""
    from utils.opensearch_queries import build_rename_collision_query
    from utils.file_utils import get_filename_aliases

    candidates = get_filename_aliases(new_filename)
    if not candidates:
        return False
    query = build_rename_collision_query(
        owner_user_id, candidates, exclude_document_id
    )
    try:
        n = await _count_chunks_for_query(opensearch_client, index_name, query)
        return n > 0
    except Exception as search_err:
        if "index_not_found_exception" in str(search_err):
            await _ensure_index_exists(jwt_token)
            return False
        raise


async def _distinct_document_ids_in_chunks(
    opensearch_client,
    index_name: str,
    base_query: dict,
    sample_size: int = 2000,
) -> tuple[set[str], bool]:
    """
    From chunks matching base_query, return (non_empty_ids, empty_id_chunk_present).
    Uses a bounded sample; enough to detect 0 / 1 / many distinct ids for validation.
    """
    resp = await opensearch_client.search(
        index=index_name,
        body={
            "query": base_query,
            "size": sample_size,
            "_source": ["document_id"],
            "track_total_hits": True,
        },
    )
    hits = resp.get("hits", {}).get("hits", [])
    non_empty: set[str] = set()
    saw_empty = False
    for h in hits:
        src = h.get("_source") or {}
        did = src.get("document_id")
        if did is None or (isinstance(did, str) and not did.strip()):
            saw_empty = True
        else:
            non_empty.add(str(did).strip())
    return non_empty, saw_empty


async def rename_document_chunks_core(
    current_filename: str,
    new_filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
    document_id: str | None = None,
):
    """
    Rename display filename on all matching chunks (document_id is never modified).
    Scoped by owner + current filename aliases; optional document_id must match
    every chunk when provided.
    """
    from config.settings import get_index_name
    from utils.file_utils import get_filename_aliases
    from utils.opensearch_queries import (
        build_document_id_match_query,
        build_document_id_not_matching_filenames_query,
        build_rename_match_query,
        build_rename_source_url_match_query,
    )

    current = (current_filename or "").strip()
    new_name = (new_filename or "").strip()
    doc_id_opt = (document_id or "").strip() or None

    if not current or not new_name:
        return (
            {
                "success": False,
                "updated_chunks": 0,
                "old_filename": current,
                "new_filename": new_name,
                "error": "current_filename and new_filename are required",
            },
            400,
        )

    if current == new_name:
        return (
            {
                "success": False,
                "updated_chunks": 0,
                "old_filename": current,
                "new_filename": new_name,
                "error": "New filename must differ from the current filename",
            },
            400,
        )

    aliases = get_filename_aliases(current)
    if not aliases:
        return (
            {
                "success": False,
                "updated_chunks": 0,
                "old_filename": current,
                "new_filename": new_name,
                "error": "Invalid current filename",
            },
            400,
        )

    new_aliases = get_filename_aliases(new_name)

    effective_doc_id: str | None = None
    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )
        index_name = get_index_name()

        query_all = build_rename_match_query(user_id, aliases, None)
        total = await _count_chunks_for_query(opensearch_client, index_name, query_all)

        # UI may group rows by source_url when filename is empty; `current` can be a URL.
        if total == 0 and current.lower().startswith(("http://", "https://")):
            q_url = build_rename_source_url_match_query(user_id, current, None)
            n_url = await _count_chunks_for_query(
                opensearch_client, index_name, q_url
            )
            if n_url > 0:
                query_all = q_url
                total = n_url

        if total == 0:
            # After a partial rename, no chunk may still use `current` (all carry
            # `new_name`) so the "old name" query returns 0. If the client did not
            # keep document_id, discover it from chunks that already use the target
            # filename so the resume-by-document_id path can run.
            if not doc_id_opt and new_aliases:
                q_new = build_rename_match_query(user_id, new_aliases, None)
                sampled = await _sample_document_id_from_query(
                    opensearch_client, index_name, q_new
                )
                if sampled:
                    doc_id_opt = sampled
            if not doc_id_opt or not new_aliases:
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": (
                            "No matching document chunks found for the current filename; "
                            "pass document_id to retry after a partial rename"
                        ),
                        "document_id": doc_id_opt,
                    },
                    404,
                )

            q_doc = build_document_id_match_query(user_id, doc_id_opt)
            n_doc = await _count_chunks_for_query(
                opensearch_client, index_name, q_doc
            )
            if n_doc == 0:
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": (
                            "No chunks found for this document_id; "
                            "it may be wrong or the file was removed"
                        ),
                        "document_id": doc_id_opt,
                    },
                    404,
                )

            q_not_target = build_document_id_not_matching_filenames_query(
                user_id, doc_id_opt, new_aliases
            )
            n_not_target = await _count_chunks_for_query(
                opensearch_client, index_name, q_not_target
            )
            if n_not_target == 0:
                logger.info(
                    "Rename idempotent: every chunk already uses target filename",
                    user_id=user_id,
                    document_id=doc_id_opt,
                    new_filename=new_name,
                )
                sync_ok, sync_error = await _sync_knowledge_filters_after_rename(
                    session_manager,
                    user_id,
                    jwt_token,
                    current,
                    new_name,
                    doc_id_opt,
                )
                return (
                    {
                        "success": True,
                        "partial": False,
                        "idempotent": True,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": None,
                        "warning": None if sync_ok else sync_error,
                        "document_id": doc_id_opt,
                    },
                    200,
                )

            effective_doc_id = doc_id_opt

            if await _rename_target_filename_taken(
                opensearch_client,
                index_name,
                user_id,
                new_name,
                effective_doc_id,
                jwt_token,
            ):
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": f"A document named '{new_name}' already exists",
                        "document_id": effective_doc_id,
                    },
                    409,
                )

            ubq_resume = {
                "query": q_not_target,
                "script": {
                    "source": "ctx._source.filename = params.nn",
                    "lang": "painless",
                    "params": {"nn": new_name},
                },
            }
            resume_max_attempts = 3
            total_updated = 0
            remaining_not = n_not_target
            for attempt in range(resume_max_attempts):
                result = await opensearch_client.update_by_query(
                    index=index_name,
                    body=ubq_resume,
                    conflicts="proceed",
                    refresh=True,
                )
                batch_updated = int(result.get("updated", 0) or 0)
                total_updated += batch_updated
                if attempt == 0 and batch_updated == 0 and n_not_target > 0:
                    return (
                        {
                            "success": False,
                            "updated_chunks": 0,
                            "old_filename": current,
                            "new_filename": new_name,
                            "error": "Rename did not update any chunks; please retry",
                            "document_id": effective_doc_id,
                        },
                        500,
                    )
                remaining_not = await _count_chunks_for_query(
                    opensearch_client, index_name, q_not_target
                )
                if remaining_not == 0:
                    logger.info(
                        "Resumed rename by document_id (current name not in index)",
                        user_id=user_id,
                        updated=total_updated,
                        document_id=doc_id_opt,
                        new_filename=new_name,
                    )
                    sync_ok, sync_error = await _sync_knowledge_filters_after_rename(
                        session_manager,
                        user_id,
                        jwt_token,
                        current,
                        new_name,
                        effective_doc_id,
                    )
                    return (
                        {
                            "success": True,
                            "partial": False,
                            "idempotent": False,
                            "resumed": True,
                            "updated_chunks": total_updated,
                            "old_filename": current,
                            "new_filename": new_name,
                            "error": None,
                            "warning": None if sync_ok else sync_error,
                            "document_id": effective_doc_id,
                        },
                        200,
                    )
                if batch_updated == 0:
                    break

            logger.error(
                "Resume rename incomplete: chunks still not at target filename",
                remaining=remaining_not,
                updated_chunks=total_updated,
                document_id=doc_id_opt,
                user_id=user_id,
            )
            return (
                {
                    "success": False,
                    "partial": True,
                    "updated_chunks": total_updated,
                    "remaining_old_chunks": remaining_not,
                    "matched_chunks": n_doc,
                    "old_filename": current,
                    "new_filename": new_name,
                    "error": (
                        f"Rename applied to some chunks only ({total_updated} updated, "
                        f"{remaining_not} still need the new name). Save again to retry."
                    ),
                    "document_id": effective_doc_id,
                },
                422,
            )

        resolved_ids, _saw_empty_doc_id = await _distinct_document_ids_in_chunks(
            opensearch_client, index_name, query_all
        )
        effective_doc_id = doc_id_opt
        if effective_doc_id is None and len(resolved_ids) == 1:
            effective_doc_id = next(iter(resolved_ids))
        elif effective_doc_id is None and len(resolved_ids) > 1:
            return (
                {
                    "success": False,
                    "updated_chunks": 0,
                    "old_filename": current,
                    "new_filename": new_name,
                    "error": (
                        "Multiple documents share this filename; pass document_id "
                        "to choose which file to rename"
                    ),
                    "document_id": doc_id_opt,
                },
                400,
            )
        if doc_id_opt is None and _saw_empty_doc_id:
            return (
                {
                    "success": False,
                    "updated_chunks": 0,
                    "old_filename": current,
                    "new_filename": new_name,
                    "error": (
                        "Some chunks for this file do not have document_id; "
                        "re-index so all chunks are identifiable before renaming"
                    ),
                    "document_id": effective_doc_id,
                },
                400,
            )
        if doc_id_opt and effective_doc_id and doc_id_opt != effective_doc_id:
            return (
                {
                    "success": False,
                    "updated_chunks": 0,
                    "old_filename": current,
                    "new_filename": new_name,
                    "error": "document_id does not match chunks for this filename",
                    "document_id": effective_doc_id,
                },
                400,
            )

        query_apply = query_all
        matched_total = total
        if effective_doc_id:
            query_strict = build_rename_match_query(user_id, aliases, effective_doc_id)
            strict_total = await _count_chunks_for_query(
                opensearch_client, index_name, query_strict
            )
            if strict_total == 0:
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": "document_id does not match any chunks for this filename",
                        "document_id": effective_doc_id,
                    },
                    400,
                )
            if strict_total != total:
                if doc_id_opt:
                    return (
                        {
                            "success": False,
                            "updated_chunks": 0,
                            "old_filename": current,
                            "new_filename": new_name,
                            "error": (
                                "Some chunks for this file lack the given document_id; "
                                "retry without document_id"
                            ),
                            "document_id": effective_doc_id,
                        },
                        400,
                    )
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": (
                            "Some chunks for this file lack document_id; re-index or "
                            "pass document_id after it is present on all chunks"
                        ),
                        "document_id": effective_doc_id,
                    },
                    400,
                )
            query_apply = query_strict
            matched_total = strict_total

        collision_exclude = effective_doc_id if effective_doc_id else None
        if await _rename_target_filename_taken(
            opensearch_client,
            index_name,
            user_id,
            new_name,
            collision_exclude,
            jwt_token,
        ):
            return (
                {
                    "success": False,
                    "updated_chunks": 0,
                    "old_filename": current,
                    "new_filename": new_name,
                    "error": f"A document named '{new_name}' already exists",
                    "document_id": effective_doc_id,
                },
                409,
            )

        # Only update display filename; document_id and all other fields (filters, dedup) stay the same.
        ubq_body = {
            "query": query_apply,
            "script": {
                "source": "ctx._source.filename = params.nn",
                "lang": "painless",
                "params": {"nn": new_name},
            },
        }

        rename_ubq_max_attempts = 3
        total_updated = 0
        remaining_old = 0

        for attempt in range(rename_ubq_max_attempts):
            result = await opensearch_client.update_by_query(
                index=index_name,
                body=ubq_body,
                conflicts="proceed",
                refresh=True,
            )
            batch_updated = int(result.get("updated", 0) or 0)
            total_updated += batch_updated

            if attempt == 0 and batch_updated == 0 and matched_total > 0:
                return (
                    {
                        "success": False,
                        "updated_chunks": 0,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": "Rename did not update any chunks; please retry",
                        "document_id": effective_doc_id,
                    },
                    500,
                )

            remaining_old = await _count_chunks_for_query(
                opensearch_client, index_name, query_apply
            )
            if remaining_old == 0:
                logger.info(
                    "Renamed document chunks",
                    user_id=user_id,
                    updated=total_updated,
                    attempts=attempt + 1,
                    old_filename=current,
                    new_filename=new_name,
                )
                sync_ok, sync_error = await _sync_knowledge_filters_after_rename(
                    session_manager,
                    user_id,
                    jwt_token,
                    current,
                    new_name,
                    effective_doc_id,
                )
                return (
                    {
                        "success": True,
                        "partial": False,
                        "updated_chunks": total_updated,
                        "old_filename": current,
                        "new_filename": new_name,
                        "error": None,
                        "warning": None if sync_ok else sync_error,
                        "document_id": effective_doc_id,
                    },
                    200,
                )
            if batch_updated == 0:
                break

        logger.error(
            "Rename incomplete: old filename still present after update(s)",
            remaining=remaining_old,
            updated_chunks=total_updated,
            attempts=rename_ubq_max_attempts,
            user_id=user_id,
        )
        report_doc_id = effective_doc_id
        if report_doc_id is None:
            report_doc_id = await _sample_document_id_from_query(
                opensearch_client, index_name, query_apply
            )
        return (
            {
                "success": False,
                "partial": True,
                "updated_chunks": total_updated,
                "remaining_old_chunks": remaining_old,
                "matched_chunks": matched_total,
                "old_filename": current,
                "new_filename": new_name,
                "error": (
                    f"Rename applied to some chunks only ({total_updated} updated, "
                    f"{remaining_old} still use the old name). Save again to retry."
                ),
                "document_id": report_doc_id,
            },
            422,
        )
    except Exception as e:
        logger.error(
            "Error renaming document chunks",
            current_filename=current,
            new_filename=new_name,
            error=str(e),
        )
        error_str = str(e)
        status_code = 403 if "AuthenticationException" in error_str else 500
        return (
            {
                "success": False,
                "updated_chunks": 0,
                "old_filename": current,
                "new_filename": new_name,
                "error": (
                    "Access denied: insufficient permissions"
                    if status_code == 403
                    else "An internal error has occurred while renaming the document"
                ),
                "document_id": effective_doc_id,
            },
            status_code,
        )


async def _ensure_index_exists(jwt_token: str = None):
    """Create the OpenSearch index if it doesn't exist yet."""
    from main import init_index
    from config.settings import IBM_AUTH_ENABLED, clients as app_clients

    opensearch_client = None
    if IBM_AUTH_ENABLED and jwt_token:
        opensearch_client = app_clients.create_user_opensearch_client(jwt_token)

    await init_index(opensearch_client)


async def check_filename_exists(
    filename: str,
    content_hash: str | None = None,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Check if a document with a specific filename already exists"""
    from config.settings import get_index_name

    jwt_token = user.jwt_token

    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user.user_id, jwt_token
        )
        normalized_content_hash = (content_hash or "").strip()
        if normalized_content_hash:
            by_hash_response = await opensearch_client.search(
                index=get_index_name(),
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"document_id": normalized_content_hash}},
                                {"term": {"owner": user.user_id}},
                            ]
                        }
                    },
                    "size": 1,
                    "_source": False,
                },
            )
            by_hash_exists = (
                len(by_hash_response.get("hits", {}).get("hits", [])) > 0
            )
            if by_hash_exists:
                return JSONResponse(
                    {
                        "exists": True,
                        "filename": filename,
                        "match_type": "content_hash",
                    },
                    status_code=200,
                )

        from utils.opensearch_queries import build_filename_search_body
        from utils.file_utils import get_filename_aliases

        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return JSONResponse(
                {"exists": False, "filename": filename, "match_type": "filename"},
                status_code=200,
            )

        logger.debug("Checking filename existence", filename=filename, index_name=get_index_name())
        exists = False

        try:
            for candidate in candidate_filenames:
                search_body = build_filename_search_body(candidate, size=1, source=["filename"])
                response = await opensearch_client.search(
                    index=get_index_name(),
                    body=search_body
                )
                hits = response.get("hits", {}).get("hits", [])
                if hits:
                    exists = True
                    break
        except Exception as search_err:
            if "index_not_found_exception" in str(search_err):
                logger.info("Index does not exist, creating it now before upload")
                await _ensure_index_exists(jwt_token)
                return JSONResponse(
                    {"exists": False, "filename": filename, "match_type": "filename"},
                    status_code=200,
                )
            raise

        return JSONResponse(
            {"exists": exists, "filename": filename, "match_type": "filename"},
            status_code=200,
        )

    except Exception as e:
        logger.error("Error checking filename existence", filename=filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse({"error": "Access denied: insufficient permissions"}, status_code=403)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)


async def rename_document(
    body: RenameDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Rename display filename on all chunks (document_id is not modified)."""
    payload, status_code = await rename_document_chunks_core(
        current_filename=body.current_filename,
        new_filename=body.new_filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=user.jwt_token,
        document_id=body.document_id,
    )
    return JSONResponse(payload, status_code=status_code)


async def delete_documents_by_filename(
    body: DeleteDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
    ):
    """Delete all documents with a specific filename"""
    payload, status_code =await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=user.jwt_token,
    )
    return JSONResponse(payload, status_code=status_code)
