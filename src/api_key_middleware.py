"""
API Key middleware for authenticating public API requests.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _extract_api_key(request: Request) -> str | None:
    """
    Extract API key from request headers.

    Supports:
    - X-API-Key header
    - Authorization: Bearer orag_... header
    """
    # Try X-API-Key header first
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key.startswith("orag_"):
        return api_key

    # Try Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
        if token.startswith("orag_"):
            return token

    return None


def require_api_key(api_key_service):
    """
    Decorator to require API key authentication for public API endpoints.

    Usage:
        @require_api_key(api_key_service)
        async def my_endpoint(request):
            user = request.state.user
            ...
    """

    def decorator(handler):
        async def wrapper(request: Request):
            # Extract API key from headers
            api_key = _extract_api_key(request)

            if not api_key:
                return JSONResponse(
                    {
                        "error": "API key required",
                        "message": "Provide API key via X-API-Key header or Authorization: Bearer header",
                    },
                    status_code=401,
                )

            # Validate the key
            user_info = await api_key_service.validate_key(api_key)

            if not user_info:
                return JSONResponse(
                    {
                        "error": "Invalid API key",
                        "message": "The provided API key is invalid or has been revoked",
                    },
                    status_code=401,
                )

            # Create a User object from the API key info
            user = User(
                user_id=user_info["user_id"],
                email=user_info["user_email"],
                name=user_info.get("name", "API User"),
                picture=None,
                provider="api_key",
            )

            # Set request state
            request.state.user = user
            request.state.api_key_id = user_info["key_id"]
            request.state.jwt_token = None  # No JWT for API key auth

            return await handler(request)

        return wrapper

    return decorator


def optional_api_key(api_key_service):
    """
    Decorator to optionally authenticate with API key.
    Sets request.state.user to None if no valid API key is provided.
    """

    def decorator(handler):
        async def wrapper(request: Request):
            # Extract API key from headers
            api_key = _extract_api_key(request)

            if api_key:
                # Validate the key
                user_info = await api_key_service.validate_key(api_key)

                if user_info:
                    # Create a User object from the API key info
                    user = User(
                        user_id=user_info["user_id"],
                        email=user_info["user_email"],
                        name=user_info.get("name", "API User"),
                        picture=None,
                        provider="api_key",
                    )
                    request.state.user = user
                    request.state.api_key_id = user_info["key_id"]
                    request.state.jwt_token = None
                else:
                    request.state.user = None
                    request.state.api_key_id = None
                    request.state.jwt_token = None
            else:
                request.state.user = None
                request.state.api_key_id = None
                request.state.jwt_token = None

            return await handler(request)

        return wrapper

    return decorator
