"""Authenticated downloads for original files retained by local ingestion."""

from __future__ import annotations

import mimetypes
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from config.settings import get_index_name
from dependencies import get_current_user, get_session_manager
from services.local_source_service import document_id_from_source_id, find_local_source
from session_manager import User

PREVIEWABLE_MEDIA_TYPES = {
    "application/json",
    "application/pdf",
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/markdown",
    "text/plain",
}


def _total_hits(response: dict[str, Any]) -> int:
    """Return the total hit count from an OpenSearch response."""
    total = response.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        total = total.get("value", 0)
    return int(total) if isinstance(total, int) else 0


async def download_local_source(
    source_id: str,
    session_manager: Annotated[Any, Depends(get_session_manager)],
    user: Annotated[User, Depends(get_current_user)],
    preview: bool = False,
):
    """Serve a retained original only when the caller can read its chunks."""
    document_id = document_id_from_source_id(source_id)
    if document_id is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    result = await opensearch_client.search(
        index=get_index_name(),
        body={
            "size": 0,
            "track_total_hits": 1,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"document_id": document_id}},
                        {
                            "wildcard": {
                                "source_url": {
                                    "value": f"*/api/source-files/{source_id}",
                                }
                            }
                        },
                    ]
                }
            },
        },
    )
    if _total_hits(result) == 0:
        raise HTTPException(status_code=404, detail="Source file not found")

    source = find_local_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    if preview and media_type not in PREVIEWABLE_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Source preview is not supported")

    return FileResponse(
        source,
        media_type=media_type,
        filename=source.name,
        content_disposition_type="inline" if preview else "attachment",
        headers={"Cache-Control": "private, no-store"},
    )
