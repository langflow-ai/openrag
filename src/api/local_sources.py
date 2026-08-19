"""Authenticated downloads for original files retained by local ingestion."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from config.settings import get_index_name
from dependencies import get_current_user, get_session_manager
from services.local_source_service import (
    LocalSourceNotFoundError,
    LocalSourcePreviewUnsupportedError,
    resolve_local_source_download,
)
from session_manager import User


async def download_local_source(
    source_id: str,
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(get_current_user)],
    preview: bool = False,
):
    """Serve a retained original only when the caller can read its chunks."""
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    try:
        source = await resolve_local_source_download(
            source_id,
            opensearch_client=opensearch_client,
            index=get_index_name(),
            preview=preview,
        )
    except LocalSourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source file not found") from None
    except LocalSourcePreviewUnsupportedError:
        raise HTTPException(status_code=415, detail="Source preview is not supported") from None

    return FileResponse(
        source.path,
        media_type=source.media_type,
        filename=source.path.name,
        content_disposition_type="inline" if preview else "attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
