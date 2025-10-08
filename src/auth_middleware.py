from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Optional
from session_manager import User
from config.settings import is_no_auth_mode
from utils.logging_config import get_logger

logger = get_logger(__name__)


def get_current_user(request: Request, session_manager) -> Optional[User]:
    """Extract current user from request cookies"""
    # In no-auth mode, ignore cookies entirely
    if is_no_auth_mode():
        return None

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        return None

    return session_manager.get_user_from_token(auth_token)


def require_auth(session_manager):
    """Decorator to require authentication for endpoints"""

    def decorator(handler):
        async def wrapper(request: Request):
            # In no-auth mode, bypass authentication entirely
            if is_no_auth_mode():
                # Create an anonymous user object so endpoints don't break
                from session_manager import User
                from datetime import datetime

                from session_manager import AnonymousUser
                request.state.user = AnonymousUser()
                request.state.jwt_token = None  # No JWT in no-auth mode
                return await handler(request)

            user = get_current_user(request, session_manager)
            if not user:
                return JSONResponse(
                    {"error": "Authentication required"}, status_code=401
                )

            # Add user and JWT token to request state so handlers can access them
            request.state.user = user
            request.state.jwt_token = (
                None if is_no_auth_mode() else request.cookies.get("auth_token")
            )
            return await handler(request)

        return wrapper

    return decorator


def optional_auth(session_manager):
    """Decorator to optionally extract user for endpoints"""

    def decorator(handler):
        async def wrapper(request: Request):
            # In no-auth mode, create anonymous user
            if is_no_auth_mode():
                # Create an anonymous user object so endpoints don't break
                from session_manager import User
                from datetime import datetime

                from session_manager import AnonymousUser
                request.state.user = AnonymousUser()
                request.state.jwt_token = None  # No JWT in no-auth mode
            else:
                user = get_current_user(request, session_manager)
                request.state.user = user  # Can be None
                request.state.jwt_token = (
                    None
                    if is_no_auth_mode()
                    else (request.cookies.get("auth_token") if user else None)
                )
            return await handler(request)

        return wrapper

    return decorator
