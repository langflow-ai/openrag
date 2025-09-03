"""
Authentication context for tool functions.
Uses contextvars to safely pass user auth info through async calls.
"""

from contextvars import ContextVar
from typing import Optional, Dict, Any

# Context variables for current request authentication
_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id", default=None
)
_current_jwt_token: ContextVar[Optional[str]] = ContextVar(
    "current_jwt_token", default=None
)
_current_search_filters: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "current_search_filters", default=None
)
_current_search_limit: ContextVar[Optional[int]] = ContextVar(
    "current_search_limit", default=10
)
_current_score_threshold: ContextVar[Optional[float]] = ContextVar(
    "current_score_threshold", default=0
)


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


def set_search_filters(filters: Dict[str, Any]):
    """Set search filters for the current async context"""
    _current_search_filters.set(filters)


def get_search_filters() -> Optional[Dict[str, Any]]:
    """Get current search filters from context"""
    return _current_search_filters.get()


def set_search_limit(limit: int):
    """Set search limit for the current async context"""
    _current_search_limit.set(limit)


def get_search_limit() -> int:
    """Get current search limit from context"""
    return _current_search_limit.get()


def set_score_threshold(threshold: float):
    """Set score threshold for the current async context"""
    _current_score_threshold.set(threshold)


def get_score_threshold() -> float:
    """Get current score threshold from context"""
    return _current_score_threshold.get()
