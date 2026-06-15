from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dependencies import get_current_user, get_session_manager, require_permission
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


class DeleteDocumentBody(BaseModel):
    filename: str


async def delete_documents_by_filename_core(
    filename: str,
    session_manager,
    user_id: str,
    jwt_token: str | None,
):
    """Shared delete-by-filename logic for v1 and non-v1 endpoints."""
    from config.settings import get_index_name
    from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids
    from utils.opensearch_queries import build_filename_query, build_owned_filename_query

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
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)
        index_name = get_index_name()

        owned_document_ids = await collect_visible_document_ids(
            opensearch_client,
            index=index_name,
            query=build_owned_filename_query(normalized_filename, user_id),
        )

        if not owned_document_ids:
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

        from config.settings import clients

        deleted_count = await delete_document_ids(
            clients.opensearch,
            index=index_name,
            document_ids=owned_document_ids,
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


async def delete_chunks_by_document_ids(
    document_ids: list[str],
    opensearch_client,
    index_name: str,
    write_opensearch_client=None,
    field: str = "document_id",
) -> int:
    """Bulk delete OpenSearch chunks by a keyword field. Returns deleted count.

    DLS-safe: enumerate the visible chunk _ids via search, then issue a trusted
    delete per primary id. `delete_by_query` is silently no-opped under DLS
    (returns deleted:N but leaves docs in place).

    `field` selects which indexed keyword to match against (default: ``document_id``).
    Pass ``field="connector_file_id"`` to clean up chunks for a deleted connector
    source file when the connector file ID differs from the content hash stored in
    ``document_id``.
    """
    if not document_ids:
        return 0
    from config.settings import clients
    from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids

    chunk_ids = await collect_visible_document_ids(
        opensearch_client,
        index=index_name,
        query={"terms": {field: document_ids}},
    )
    write_client = write_opensearch_client or clients.opensearch
    if write_client is None:
        raise RuntimeError("Backend OpenSearch write client is unavailable")
    return await delete_document_ids(
        write_client,
        index=index_name,
        document_ids=chunk_ids,
        refresh=True,
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

        from utils.file_utils import get_filename_aliases
        from utils.opensearch_queries import build_filename_search_body

        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return JSONResponse({"exists": False, "filename": filename}, status_code=200)

        logger.debug("Checking filename existence", filename=filename, index_name=get_index_name())
        exists = False

        try:
            for candidate in candidate_filenames:
                search_body = build_filename_search_body(candidate, size=1, source=["filename"])
                response = await opensearch_client.search(index=get_index_name(), body=search_body)
                hits = response.get("hits", {}).get("hits", [])
                if hits:
                    exists = True
                    break
        except Exception as search_err:
            if "index_not_found_exception" in str(search_err):
                logger.info("Index does not exist, creating it now before upload")
                await _ensure_index_exists(jwt_token)
                return JSONResponse({"exists": False, "filename": filename}, status_code=200)
            raise

        return JSONResponse({"exists": exists, "filename": filename}, status_code=200)

    except Exception as e:
        logger.error("Error checking filename existence", filename=filename, error=str(e))
        error_str = str(e)
        if "AuthenticationException" in error_str:
            return JSONResponse(
                {"error": "Access denied: insufficient permissions"}, status_code=403
            )
        else:
            return JSONResponse({"error": str(e)}, status_code=500)


async def delete_documents_by_filename(
    body: DeleteDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("knowledge:delete:own")),
):
    """Delete all documents with a specific filename"""
    payload, status_code = await delete_documents_by_filename_core(
        filename=body.filename,
        session_manager=session_manager,
        user_id=user.user_id,
        jwt_token=user.jwt_token,
    )
    return JSONResponse(payload, status_code=status_code)
