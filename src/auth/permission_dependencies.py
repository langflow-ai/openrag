"""Permission enforcement helpers for request identity dependencies."""

import dataclasses
from collections.abc import Sequence

from fastapi import HTTPException, Request

from auth.request_identity import _attach_db_user_id
from auth.user_identity_cache import _resolve_db_user_id
from session_manager import User


async def enforce_permission(request: Request, user: User, rbac, perm: str) -> User:
    """Enforce one browser-authenticated permission."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        # RBAC kill-switch: still resolve the DB id so downstream
        # ownership checks that compare against it keep working.
        return await _attach_db_user_id(request, user)
    role_override = getattr(request.state, "api_key_role_ids", None)
    db_user_id = await _resolve_db_user_id(user)
    user = dataclasses.replace(user, db_user_id=db_user_id)
    request.state.db_user_id = db_user_id
    request.state.user = user
    perms = await rbac.get_user_permissions(db_user_id, role_override=role_override)
    if perm not in perms:
        await rbac.audit_denied(db_user_id, perm)
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": perm},
        )
    return user


async def enforce_any_permission(
    request: Request,
    user: User,
    rbac,
    required: Sequence[str],
) -> User:
    """Require at least one browser-authenticated permission."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        return await _attach_db_user_id(request, user)
    role_override = getattr(request.state, "api_key_role_ids", None)
    db_user_id = await _resolve_db_user_id(user)
    user = dataclasses.replace(user, db_user_id=db_user_id)
    request.state.db_user_id = db_user_id
    request.state.user = user
    perms = await rbac.get_user_permissions(db_user_id, role_override=role_override)
    if not any(perm in perms for perm in required):
        await rbac.audit_denied(db_user_id, "|".join(required))
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": list(required)},
        )
    return user


async def enforce_all_permissions(
    request: Request,
    user: User,
    rbac,
    required: Sequence[str],
) -> User:
    """Require all listed browser-authenticated permissions."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        return await _attach_db_user_id(request, user)
    role_override = getattr(request.state, "api_key_role_ids", None)
    db_user_id = await _resolve_db_user_id(user)
    user = dataclasses.replace(user, db_user_id=db_user_id)
    request.state.db_user_id = db_user_id
    request.state.user = user
    perms = await rbac.get_user_permissions(db_user_id, role_override=role_override)
    missing = [perm for perm in required if perm not in perms]
    if missing:
        await rbac.audit_denied(db_user_id, ",".join(missing))
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": list(required)},
        )
    return user


async def enforce_api_key_permission(request: Request, user: User, rbac, perm: str) -> User:
    """Enforce one API-key or forwarded-JWT permission."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        return user
    db_user_id = user.db_user_id or user.user_id
    role_override = getattr(request.state, "api_key_role_ids", None)
    perms = await rbac.get_user_permissions(db_user_id, role_override=role_override)
    if perm not in perms:
        await rbac.audit_denied(db_user_id, perm)
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": perm},
        )
    return user


async def enforce_api_key_any_permission(
    request: Request,
    user: User,
    rbac,
    required: Sequence[str],
) -> User:
    """Require at least one API-key or forwarded-JWT permission."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        return user
    db_user_id = user.db_user_id or user.user_id
    role_override = getattr(request.state, "api_key_role_ids", None)
    perms = await rbac.get_user_permissions(db_user_id, role_override=role_override)
    if not any(perm in perms for perm in required):
        await rbac.audit_denied(db_user_id, "|".join(required))
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "required": list(required)},
        )
    return user


async def has_effective_permission(
    request: Request,
    user: User,
    rbac,
    perm: str,
) -> bool:
    """Check a permission using the same RBAC and API-key override semantics as route gates."""
    from services.rbac_service import is_rbac_enforced

    if not is_rbac_enforced():
        return True
    user_id = user.db_user_id or user.user_id
    role_override = getattr(request.state, "api_key_role_ids", None)
    return await rbac.has_permission(user_id, perm, role_override=role_override)
