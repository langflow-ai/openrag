from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dependencies import (
    get_current_user,
    get_rbac_service,
    get_session_manager,
    has_effective_permission,
    require_any_permission,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

require_document_delete_permission = require_any_permission(
    ("knowledge:delete:own", "knowledge:delete:anonymous")
)


class DeleteDocumentBody(BaseModel):
    filename: str


async def delete_documents_by_filename_core(
    filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
    can_delete_own: bool = True,
    can_delete_anonymous: bool = False,
):
    """Shared delete-by-filename logic for v1 and non-v1 endpoints."""
    from config.settings import get_index_name
    from services.local_source_service import (
        delete_local_source,
        source_id_from_local_source_url,
    )
    from utils.opensearch_delete import collect_visible_document_hits, delete_document_ids
    from utils.opensearch_queries import (
        build_anonymous_filename_query,
        build_filename_query,
        build_owned_filename_query,
        build_replace_filename_query,
    )

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
        index_name = get_index_name()
        from config.settings import clients

        write_client = clients.opensearch

        if can_delete_own and can_delete_anonymous:
            if write_client is None:
                raise RuntimeError("Backend OpenSearch client is unavailable")
            document_hits = await collect_visible_document_hits(
                write_client,
                index=index_name,
                query=build_replace_filename_query(normalized_filename, user_id),
                source=["document_id", "source_url"],
            )
        elif can_delete_anonymous:
            if write_client is None:
                raise RuntimeError("Backend OpenSearch client is unavailable")
            document_hits = await collect_visible_document_hits(
                write_client,
                index=index_name,
                query=build_anonymous_filename_query(normalized_filename),
                source=["document_id", "source_url"],
            )
        elif can_delete_own:
            opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)
            document_hits = await collect_visible_document_hits(
                opensearch_client,
                index=index_name,
                query=build_owned_filename_query(normalized_filename, user_id),
                source=["document_id", "source_url"],
            )
        else:
            return (
                {
                    "success": False,
                    "deleted_chunks": 0,
                    "filename": normalized_filename,
                    "message": None,
                    "error": "Access denied: insufficient permissions",
                },
                403,
            )

        if not document_hits:
            if can_delete_anonymous:
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
            visible_check = await opensearch_client.search(
                index=index_name,
                body={
                    "query": build_filename_query(normalized_filename),
                    "size": 1,
                    "_source": ["owner"],
                },
            )
            if visible_check.get("hits", {}).get("hits", []):
                return (
                    {
                        "success": False,
                        "deleted_chunks": 0,
                        "filename": normalized_filename,
                        "message": None,
                        "error": "Access denied: only the document owner can delete this file",
                    },
                    403,
                )

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

        document_ids = [hit["_id"] for hit in document_hits]
        local_source_ids = {
            source_id
            for hit in document_hits
            if (source := hit.get("_source", {}))
            if (source_id := source_id_from_local_source_url(source.get("source_url")))
            if source.get("document_id") == source_id.rsplit(".", 1)[0]
        }

        if write_client is None:
            raise RuntimeError("Backend OpenSearch client is unavailable")
        deleted_count = await delete_document_ids(
            write_client,
            index=index_name,
            document_ids=document_ids,
        )
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

        # Source lifecycle contract:
        # - Want/why: deleting knowledge must not leave its retained original behind.
        # - How: remove only validated local archives after refreshed chunk deletion
        #   and only when the source has no remaining index reference.
        # - Compatibility/KISS: remote connector URLs are ignored; no new database or
        #   background cleanup process is introduced.
        deleted_sources = 0
        for source_id in local_source_ids:
            try:
                remaining = await write_client.search(
                    index=index_name,
                    body={
                        "size": 1,
                        "_source": False,
                        "query": {
                            "wildcard": {
                                "source_url": {
                                    "value": f"*/api/source-files/{source_id}",
                                }
                            }
                        },
                    },
                )
                if remaining.get("hits", {}).get("hits", []):
                    continue
                if await delete_local_source(source_id):
                    deleted_sources += 1
            except Exception as cleanup_error:
                logger.error(
                    "Failed to delete unreferenced local source",
                    source_id=source_id,
                    error=str(cleanup_error),
                )

        if deleted_sources:
            logger.info(
                "Deleted unreferenced local sources",
                filename=normalized_filename,
                deleted_sources=deleted_sources,
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
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        is_auth_error = is_opensearch_auth_error(e)
        status_code = 401 if is_auth_error else 500
        return (
            {
                "success": False,
                "deleted_chunks": 0,
                "filename": normalized_filename,
                "message": None,
                "error": (
                    AUTH_ERROR_MESSAGE
                    if is_auth_error
                    else "An internal error has occurred while deleting documents"
                ),
            },
            status_code,
        )


async def _ensure_index_exists(jwt_token: str = None):
    """Create the OpenSearch index if it doesn't exist yet."""
    from config.settings import clients as app_clients
    from main import init_index

    # Index administration needs more privileges than the per-user client has
    # in SaaS (the end-user JWT can search/write documents but not run admin
    # calls like HEAD /<index> or index creation) — pick the admin-capable
    # client for the run mode.
    opensearch_client = app_clients.create_index_admin_opensearch_client(jwt_token)
    await init_index(opensearch_client)


async def check_filename_exists(
    filename: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Check if a document with a specific filename already exists"""
    from config.settings import get_index_name

    jwt_token = user.jwt_token

    try:
        opensearch_client = session_manager.get_user_opensearch_client(user.user_id, jwt_token)

        from utils.opensearch_filenames import filename_exists

        logger.debug("Checking filename existence", filename=filename, index_name=get_index_name())
        exists = False

        try:
            exists = await filename_exists(filename, opensearch_client, get_index_name())
        except Exception as search_err:
            if "index_not_found_exception" in str(search_err):
                logger.info("Index does not exist, creating it now before upload")
                await _ensure_index_exists(jwt_token)
                return JSONResponse({"exists": False, "filename": filename}, status_code=200)
            raise

        return JSONResponse({"exists": exists, "filename": filename}, status_code=200)

    except Exception as e:
        logger.error("Error checking filename existence", filename=filename, error=str(e))
        from utils.opensearch_utils import AUTH_ERROR_MESSAGE, is_opensearch_auth_error

        if is_opensearch_auth_error(e):
            return JSONResponse({"error": AUTH_ERROR_MESSAGE}, status_code=401)
        else:
            return JSONResponse({"error": str(e)}, status_code=500)


async def delete_documents_by_filename(
    body: DeleteDocumentBody,
    request: Request,
    session_manager=Depends(get_session_manager),
    rbac=Depends(get_rbac_service),
    user: User = Depends(require_document_delete_permission),
):
    """Delete all documents with a specific filename"""
    can_delete_own = await has_effective_permission(
        request,
        user,
        rbac,
        "knowledge:delete:own",
    )
    can_delete_anonymous = await has_effective_permission(
        request,
        user,
        rbac,
        "knowledge:delete:anonymous",
    )
    payload, status_code = await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=user.jwt_token,
        can_delete_own=can_delete_own,
        can_delete_anonymous=can_delete_anonymous,
    )
    return JSONResponse(payload, status_code=status_code)
