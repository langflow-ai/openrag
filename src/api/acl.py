from typing import List

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import get_index_name
from dependencies import get_current_user, get_session_manager
from session_manager import User
from utils.acl_utils import update_document_acl
from connectors.base import DocumentACL
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ShareDocumentBody(BaseModel):
    filename: str
    user_ids: List[str]


class UnshareDocumentBody(BaseModel):
    filename: str
    user_ids: List[str]


async def _get_acl_or_raise(
    filename: str,
    opensearch_client,
    user_id: str,
    index_name: str,
):
    """Query one chunk by filename, return _source. Raises 404/403 as tuples."""
    response = await opensearch_client.search(
        index=index_name,
        body={
            "query": {"term": {"filename": filename}},
            "size": 1,
            "_source": ["owner", "allowed_users", "allowed_groups", "document_id"],
        },
    )
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None, (
            {"error": f"Document '{filename}' not found"},
            404,
        )

    source = hits[0]["_source"]
    doc_owner = source.get("owner")
    if doc_owner and doc_owner != user_id:
        return None, (
            {"error": "Access denied: only the document owner can manage sharing"},
            403,
        )

    return source, None


async def get_document_acl(
    filename: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """GET /documents/acl?filename=... — return ACL for a document."""
    opensearch_client = session_manager.get_user_opensearch_client(
        user.user_id, user.jwt_token
    )
    source, error = await _get_acl_or_raise(
        filename, opensearch_client, user.user_id, get_index_name()
    )
    if error:
        return JSONResponse(error[0], status_code=error[1])

    return JSONResponse(
        {
            "owner": source.get("owner"),
            "allowed_users": source.get("allowed_users", []),
            "allowed_groups": source.get("allowed_groups", []),
        }
    )


async def share_document(
    body: ShareDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """POST /documents/acl/share — add user_ids to allowed_users."""
    opensearch_client = session_manager.get_user_opensearch_client(
        user.user_id, user.jwt_token
    )
    index_name = get_index_name()
    source, error = await _get_acl_or_raise(
        body.filename, opensearch_client, user.user_id, index_name
    )
    if error:
        return JSONResponse(error[0], status_code=error[1])

    existing_users = source.get("allowed_users", [])
    merged = list(dict.fromkeys(existing_users + body.user_ids))  # dedup, preserve order

    new_acl = DocumentACL(
        owner=source.get("owner"),
        allowed_users=merged,
        allowed_groups=source.get("allowed_groups", []),
    )

    document_id = source.get("document_id")
    if document_id:
        result = await update_document_acl(document_id, new_acl, opensearch_client)
    else:
        result = await opensearch_client.update_by_query(
            index=index_name,
            body={
                "query": {"term": {"filename": body.filename}},
                "script": {
                    "source": "ctx._source.allowed_users = params.allowed_users;",
                    "params": {"allowed_users": merged},
                },
            },
        )

    logger.info(
        "Shared document",
        filename=body.filename,
        owner=user.user_id,
        added_users=body.user_ids,
    )
    return JSONResponse({"success": True, "allowed_users": merged, "acl_result": str(result)})


async def unshare_document(
    body: UnshareDocumentBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """POST /documents/acl/unshare — remove user_ids from allowed_users."""
    opensearch_client = session_manager.get_user_opensearch_client(
        user.user_id, user.jwt_token
    )
    index_name = get_index_name()
    source, error = await _get_acl_or_raise(
        body.filename, opensearch_client, user.user_id, index_name
    )
    if error:
        return JSONResponse(error[0], status_code=error[1])

    remove_set = set(body.user_ids)
    remaining = [u for u in source.get("allowed_users", []) if u not in remove_set]

    new_acl = DocumentACL(
        owner=source.get("owner"),
        allowed_users=remaining,
        allowed_groups=source.get("allowed_groups", []),
    )

    document_id = source.get("document_id")
    if document_id:
        result = await update_document_acl(document_id, new_acl, opensearch_client)
    else:
        result = await opensearch_client.update_by_query(
            index=index_name,
            body={
                "query": {"term": {"filename": body.filename}},
                "script": {
                    "source": "ctx._source.allowed_users = params.allowed_users;",
                    "params": {"allowed_users": remaining},
                },
            },
        )

    logger.info(
        "Unshared document",
        filename=body.filename,
        owner=user.user_id,
        removed_users=body.user_ids,
    )
    return JSONResponse({"success": True, "allowed_users": remaining, "acl_result": str(result)})
