from fastapi import Depends
from fastapi.responses import JSONResponse

from config.settings import get_index_name
from dependencies import get_current_user, get_session_manager
from session_manager import User


async def get_document_acl(
    filename: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """GET /documents/acl?filename=... — return ACL for a document."""
    opensearch_client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    response = await opensearch_client.search(
        index=get_index_name(),
        body={
            "query": {"term": {"filename": filename}},
            "size": 1,
            "_source": ["owner", "allowed_users", "allowed_groups"],
        },
    )
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return JSONResponse(
            {"error": f"Document '{filename}' not found"},
            status_code=404,
        )

    source = hits[0]["_source"]
    return JSONResponse(
        {
            "owner": source.get("owner"),
            "allowed_users": source.get("allowed_users", []),
            "allowed_groups": source.get("allowed_groups", []),
        }
    )
