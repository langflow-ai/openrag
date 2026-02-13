"""
API Key management endpoints.

These endpoints use JWT cookie authentication (for the UI) and allow users
to create, list, and revoke their API keys for use with the public API.
"""
import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def list_keys_endpoint(request: Request, api_key_service):
    """
    List all API keys for the authenticated user.

    GET /keys

    Response:
        {
            "success": true,
            "keys": [
                {
                    "key_id": "...",
                    "key_prefix": "orag_abc12345",
                    "name": "My Key",
                    "created_at": "2024-01-01T00:00:00",
                    "last_used_at": "2024-01-02T00:00:00",
                    "revoked": false
                }
            ]
        }
    """
    user = request.state.user
    user_id = user.user_id
    jwt_token = request.state.jwt_token

    result = await api_key_service.list_keys(user_id, jwt_token)
    return JSONResponse(result)


async def create_key_endpoint(request: Request, api_key_service):
    """
    Create a new API key for the authenticated user.

    POST /keys
    Body: {"name": "My API Key"}

    Response:
        {
            "success": true,
            "key_id": "...",
            "key_prefix": "orag_abc12345",
            "name": "My API Key",
            "created_at": "2024-01-01T00:00:00",
            "api_key": "orag_abc12345..." // Full key, only shown once!
        }
    """
    user = request.state.user
    user_id = user.user_id
    user_email = user.email
    jwt_token = request.state.jwt_token

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid or missing JSON body",
                "example": {"name": "My API Key"},
            },
            status_code=400,
        )

    try:
        name = data.get("name", "").strip()

        if not name:
            return JSONResponse(
                {"success": False, "error": "Name is required"},
                status_code=400,
            )

        if len(name) > 100:
            return JSONResponse(
                {"success": False, "error": "Name must be 100 characters or less"},
                status_code=400,
            )

        result = await api_key_service.create_key(
            user_id=user_id,
            user_email=user_email,
            name=name,
            jwt_token=jwt_token,
        )

        if result.get("success"):
            return JSONResponse(result)
        else:
            return JSONResponse(result, status_code=500)

    except Exception as e:
        logger.error("Failed to create API key", error=str(e), user_id=user_id)
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


async def revoke_key_endpoint(request: Request, api_key_service):
    """
    Revoke an API key.

    DELETE /keys/{key_id}

    Response:
        {"success": true}
    """
    user = request.state.user
    user_id = user.user_id
    jwt_token = request.state.jwt_token
    key_id = request.path_params.get("key_id")

    if not key_id:
        return JSONResponse(
            {"success": False, "error": "Key ID is required"},
            status_code=400,
        )

    result = await api_key_service.revoke_key(
        user_id=user_id,
        key_id=key_id,
        jwt_token=jwt_token,
    )

    if result.get("success"):
        return JSONResponse(result)
    elif result.get("error") == "Not authorized to revoke this key":
        return JSONResponse(result, status_code=403)
    elif result.get("error") == "Key not found":
        return JSONResponse(result, status_code=404)
    else:
        return JSONResponse(result, status_code=500)


async def delete_key_endpoint(request: Request, api_key_service):
    """
    Permanently delete an API key.

    DELETE /keys/{key_id}/permanent

    Response:
        {"success": true}
    """
    user = request.state.user
    user_id = user.user_id
    jwt_token = request.state.jwt_token
    key_id = request.path_params.get("key_id")

    if not key_id:
        return JSONResponse(
            {"success": False, "error": "Key ID is required"},
            status_code=400,
        )

    result = await api_key_service.delete_key(
        user_id=user_id,
        key_id=key_id,
        jwt_token=jwt_token,
    )

    if result.get("success"):
        return JSONResponse(result)
    elif result.get("error") == "Not authorized to delete this key":
        return JSONResponse(result, status_code=403)
    elif result.get("error") == "Key not found":
        return JSONResponse(result, status_code=404)
    else:
        return JSONResponse(result, status_code=500)
