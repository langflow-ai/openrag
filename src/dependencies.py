"""
FastAPI dependency injection module.

All service dependencies and authentication dependencies live here.
Import and use these in route handlers via FastAPI's Depends() mechanism.

Usage:
    from dependencies import get_current_user, get_session_manager
    from fastapi import Depends

    async def my_endpoint(
        user = Depends(get_current_user),
        session_manager = Depends(get_session_manager),
    ):
        ...
"""

from collections.abc import AsyncIterator, Sequence

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth.permission_dependencies import (
    enforce_all_permissions,
    enforce_any_permission,
    enforce_api_key_any_permission,
    enforce_api_key_permission,
    enforce_permission,
    has_effective_permission,
)
from auth.request_identity import (
    _attach_db_user_id,
    _attach_opensearch_jwt,
    _attach_request_user,
    _get_ibm_user,
    _redact_header,
    _resolve_lakehouse_credentials,
    _stage_jwt_roles,
    resolve_api_key_user,
    resolve_current_user,
    resolve_optional_user,
)
from auth.user_identity_cache import (
    _ENSURE_LOCKS,
    _ENSURED_USER_IDS,
    _ensure_db_user,
    _resolve_db_user_id,
    _user_cache_key,
    invalidate_user_ensured_cache,
)
from session_manager import User

__all__ = [
    "_ENSURE_LOCKS",
    "_ENSURED_USER_IDS",
    "_attach_db_user_id",
    "_attach_opensearch_jwt",
    "_attach_request_user",
    "_ensure_db_user",
    "_get_ibm_user",
    "_redact_header",
    "_resolve_db_user_id",
    "_resolve_lakehouse_credentials",
    "_stage_jwt_roles",
    "_user_cache_key",
    "get_api_key_service",
    "get_api_key_user_async",
    "get_auth_service",
    "get_chat_service",
    "get_connector_service",
    "get_current_user",
    "get_db_session",
    "get_dls_principal_service",
    "get_docling_polling_service",
    "get_docling_service",
    "get_document_index_writer",
    "get_document_service",
    "get_flows_service",
    "get_group_acl_service",
    "get_knowledge_filter_service",
    "get_langflow_file_service",
    "get_langflow_ingest_token_service",
    "get_models_service",
    "get_monitor_service",
    "get_optional_user",
    "get_rbac_service",
    "get_search_service",
    "get_services",
    "get_session_manager",
    "get_task_service",
    "get_workspace_config_service",
    "has_effective_permission",
    "invalidate_user_ensured_cache",
    "require_all_permissions",
    "require_any_permission",
    "require_api_key_any_permission",
    "require_api_key_permission",
    "require_permission",
]


# ─────────────────────────────────────────────
# Service dependencies
# ─────────────────────────────────────────────


def get_services(request: Request) -> dict:
    return request.app.state.services


def get_session_manager(services: dict = Depends(get_services)):
    return services["session_manager"]


def get_auth_service(services: dict = Depends(get_services)):
    return services["auth_service"]


def get_chat_service(services: dict = Depends(get_services)):
    return services["chat_service"]


def get_search_service(services: dict = Depends(get_services)):
    return services["search_service"]


def get_document_service(services: dict = Depends(get_services)):
    return services["document_service"]


def get_task_service(services: dict = Depends(get_services)):
    return services["task_service"]


def get_knowledge_filter_service(services: dict = Depends(get_services)):
    return services["knowledge_filter_service"]


def get_monitor_service(services: dict = Depends(get_services)):
    return services["monitor_service"]


def get_connector_service(services: dict = Depends(get_services)):
    return services["connector_service"]


def get_group_acl_service(services: dict = Depends(get_services)):
    return services.get("group_acl_service")


def get_dls_principal_service(services: dict = Depends(get_services)):
    return services.get("dls_principal_service")


def get_langflow_file_service(services: dict = Depends(get_services)):
    return services["langflow_file_service"]


def get_ingest_preview_service(services: dict = Depends(get_services)):
    return services["ingest_preview_service"]


def get_document_index_writer(services: dict = Depends(get_services)):
    return services["document_index_writer"]


def get_langflow_ingest_token_service(services: dict = Depends(get_services)):
    return services["langflow_ingest_token_service"]


def get_models_service(services: dict = Depends(get_services)):
    return services["models_service"]


def get_api_key_service(services: dict = Depends(get_services)):
    return services["api_key_service"]


def get_flows_service(services: dict = Depends(get_services)):
    return services["flows_service"]


def get_docling_service(services: dict = Depends(get_services)):
    return services["docling_service"]


def get_docling_polling_service(services: dict = Depends(get_services)):
    return services["docling_polling_service"]


def get_rbac_service(services: dict = Depends(get_services)):
    return services["rbac_service"]


def get_workspace_config_service(services: dict = Depends(get_services)):
    return services["workspace_config_service"]


# ─────────────────────────────────────────────
# Database session
# ─────────────────────────────────────────────


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an async DB session for the duration of a request."""
    from db.engine import SessionLocal, init_engine

    if SessionLocal is None:
        init_engine()
    from db.engine import SessionLocal as _SessionLocal

    assert _SessionLocal is not None
    async with _SessionLocal() as session:
        yield session


async def get_current_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> User:
    """Require JWT cookie authentication."""
    return await resolve_current_user(request, session_manager)


async def get_optional_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> User | None:
    """Optionally extract JWT cookie user."""
    return await resolve_optional_user(request, session_manager)


async def get_api_key_user_async(
    request: Request,
    api_key_service=Depends(get_api_key_service),
    session_manager=Depends(get_session_manager),
) -> User:
    """Require API key or upstream authentication."""
    return await resolve_api_key_user(request, api_key_service, session_manager)


def require_permission(perm: str):
    """FastAPI dependency factory enforcing a permission on the current user."""

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        rbac=Depends(get_rbac_service),
    ) -> User:
        return await enforce_permission(request, user, rbac, perm)

    return _dep


def require_any_permission(required_perms: Sequence[str]):
    """Require at least one permission for a browser-authenticated request."""
    required = tuple(required_perms)
    if not required:
        raise ValueError("require_any_permission requires at least one permission")

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        rbac=Depends(get_rbac_service),
    ) -> User:
        return await enforce_any_permission(request, user, rbac, required)

    return _dep


def require_all_permissions(required_perms: Sequence[str]):
    """FastAPI dependency factory enforcing all listed permissions."""
    required = tuple(required_perms)
    if not required:
        raise ValueError("require_all_permissions requires at least one permission")

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        rbac=Depends(get_rbac_service),
    ) -> User:
        return await enforce_all_permissions(request, user, rbac, required)

    return _dep


def require_api_key_permission(perm: str):
    """FastAPI dependency factory enforcing one /v1 permission."""

    async def _dep(
        request: Request,
        user: User = Depends(get_api_key_user_async),
        rbac=Depends(get_rbac_service),
    ) -> User:
        return await enforce_api_key_permission(request, user, rbac, perm)

    return _dep


def require_api_key_any_permission(required_perms: Sequence[str]):
    """Require at least one permission for an API-key or forwarded-JWT request."""
    required = tuple(required_perms)
    if not required:
        raise ValueError("require_api_key_any_permission requires at least one permission")

    async def _dep(
        request: Request,
        user: User = Depends(get_api_key_user_async),
        rbac=Depends(get_rbac_service),
    ) -> User:
        return await enforce_api_key_any_permission(request, user, rbac, required)

    return _dep
