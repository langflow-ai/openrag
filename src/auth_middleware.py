from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Optional
from session_manager import User


def get_current_user(request: Request, session_manager) -> Optional[User]:
    """Extract current user from request cookies"""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        return None
    
    return session_manager.get_user_from_token(auth_token)


def require_auth(session_manager):
    """Decorator to require authentication for endpoints"""
    def decorator(handler):
        async def wrapper(request: Request):
            user = get_current_user(request, session_manager)
            if not user:
                return JSONResponse(
                    {"error": "Authentication required"}, 
                    status_code=401
                )
            
            # Add user to request state so handlers can access it
            request.state.user = user
            return await handler(request)
        
        return wrapper
    return decorator


def optional_auth(session_manager):
    """Decorator to optionally extract user for endpoints"""
    def decorator(handler):
        async def wrapper(request: Request):
            user = get_current_user(request, session_manager)
            request.state.user = user  # Can be None
            return await handler(request)
        
        return wrapper
    return decorator