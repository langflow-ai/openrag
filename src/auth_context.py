"""
Authentication context for tool functions.
Uses contextvars to safely pass user auth info through async calls.
"""
from contextvars import ContextVar
from typing import Optional

# Context variables for current request authentication
_current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)
_current_jwt_token: ContextVar[Optional[str]] = ContextVar('current_jwt_token', default=None)

def set_auth_context(user_id: str, jwt_token: str):
    """Set authentication context for the current async context"""
    _current_user_id.set(user_id)
    _current_jwt_token.set(jwt_token)

def get_current_user_id() -> Optional[str]:
    """Get current user ID from context"""
    return _current_user_id.get()

def get_current_jwt_token() -> Optional[str]:
    """Get current JWT token from context"""
    return _current_jwt_token.get()

def get_auth_context() -> tuple[Optional[str], Optional[str]]:
    """Get current authentication context (user_id, jwt_token)"""
    return _current_user_id.get(), _current_jwt_token.get()