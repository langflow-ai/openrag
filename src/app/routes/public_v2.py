"""Public /v2/* route registrations (API-key auth)."""

from fastapi import Depends, FastAPI, Query

from api.v1 import (
    chat as v1_chat,
)
from api.v2 import files as files_v2
from api.v2 import (
    chat as v2_chat,
)
from dependencies import get_file_service_v2, require_api_key_permission
from session_manager import User


async def _list_files(
    page: int = Query(
        1, ge=1, description="Page number (for display only; navigation uses after_key cursor)"
    ),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    sort_by: str = Query("filename", description="Sort field"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    search: str | None = Query(None, description="Search filename"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """List all ingested files. GET /v2/files"""
    return await files_v2.list_files(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        search=search,
        after_key=after_key,
        file_service=file_service,
        user=user,
    )


async def _search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=500, description="Items per page"),
    connector_type: str | None = Query(None, description="Filter by connector type"),
    mimetype: str | None = Query(None, description="Filter by MIME type"),
    owner: str | None = Query(None, description="Filter by owner"),
    after_key: str | None = Query(None, description="Composite pagination cursor (JSON-encoded)"),
    file_service=Depends(get_file_service_v2),
    user: User = Depends(require_api_key_permission("knowledge:read:own")),
):
    """Search ingested files by name. GET /v2/files/search"""
    return await files_v2.search_files(
        q=q,
        page=page,
        page_size=page_size,
        connector_type=connector_type,
        mimetype=mimetype,
        owner=owner,
        after_key=after_key,
        file_service=file_service,
        user=user,
    )


def register_public_v2_routes(app: FastAPI):

    # Chat v2 endpoints (with citation search_results support)
    app.add_api_route("/v2/chat", v2_chat.chat_v2_create_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v2/chat", v1_chat.chat_list_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route(
        "/v2/chat/{chat_id}",
        v1_chat.chat_get_endpoint,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v2/chat/{chat_id}",
        v1_chat.chat_delete_endpoint,
        methods=["DELETE"],
        tags=["public"],
    )

    # /v2/files/search must be registered before /v2/files to avoid path shadowing
    app.add_api_route(
        "/v2/files/search",
        _search_files,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v2/files",
        _list_files,
        methods=["GET"],
        tags=["public"],
    )

