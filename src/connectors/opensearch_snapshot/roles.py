"""Per-import OpenSearch security role and role mapping.

All security writes go through :func:`apply_role` / :func:`remove_role`, which
make zero OpenSearch calls when ``OPENRAG_SKIP_OS_SECURITY_SETUP`` is in effect
(the platform then owns the security context) and instead return the role JSON
for the platform operator to provision.
"""

from __future__ import annotations

import os
from typing import Any

from config import settings as app_settings

from .naming import role_name, slug_pattern

_SECURITY_API = "/_plugins/_security/api"
_JSON = {"Content-Type": "application/json"}


class RoleError(Exception):
    """A security API call failed. ``str()`` is user-safe."""


def security_managed_externally() -> bool:
    """True when OpenRAG must not write security config (env read per call)."""
    raw = os.getenv("OPENRAG_SKIP_OS_SECURITY_SETUP")
    if raw is None:
        return bool(getattr(app_settings, "OPENRAG_SKIP_OS_SECURITY_SETUP", False))
    return raw.strip().lower() in ("true", "1", "yes")


def role_body(slug: str) -> dict:
    return {
        "description": "OpenRAG snapshot import dataset read access",
        "cluster_permissions": [],
        "index_permissions": [
            {
                "index_patterns": [slug_pattern(slug)],
                "allowed_actions": ["read", "indices:admin/mappings/get"],
            }
        ],
    }


def role_mapping_body(principal: str | None, shared: bool) -> dict:
    """Shared: the configured shared backend role. Private: only ``principal``."""
    if shared:
        return {
            "description": "OpenRAG snapshot import (shared)",
            "backend_roles": [app_settings.get_snapshot_shared_backend_role()],
        }
    if not principal:
        raise ValueError("a private import needs an OpenSearch principal")
    return {"description": "OpenRAG snapshot import (private)", "users": [principal]}


def role_json(slug: str, principal: str | None, shared: bool) -> dict:
    name = role_name(slug)
    return {
        "role_name": name,
        "role": role_body(slug),
        "role_mapping_name": name,
        "role_mapping": role_mapping_body(principal, shared),
    }


async def _request(os_admin: Any, method: str, path: str, body: dict | None = None) -> Any:
    kwargs: dict[str, Any] = {}
    if body is not None:
        kwargs = {"body": body, "headers": _JSON}
    return await os_admin.transport.perform_request(method, path, **kwargs)


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


async def apply_role(os_admin: Any, slug: str, *, principal: str | None, shared: bool) -> dict:
    """Create/update the import's role and mapping; returns the role JSON."""
    doc = role_json(slug, principal, shared)
    if security_managed_externally():
        return doc
    try:
        await _request(os_admin, "PUT", f"{_SECURITY_API}/roles/{doc['role_name']}", doc["role"])
        await _request(
            os_admin,
            "PUT",
            f"{_SECURITY_API}/rolesmapping/{doc['role_mapping_name']}",
            doc["role_mapping"],
        )
    except Exception as exc:
        raise RoleError("the OpenSearch security API rejected the role update") from exc
    return doc


async def remove_role(os_admin: Any, slug: str) -> None:
    """Delete the import's mapping then role; missing entries are ignored."""
    if security_managed_externally():
        return
    name = role_name(slug)
    for path in (f"{_SECURITY_API}/rolesmapping/{name}", f"{_SECURITY_API}/roles/{name}"):
        try:
            await _request(os_admin, "DELETE", path)
        except Exception as exc:
            if _status_code(exc) != 404:
                raise RoleError("the OpenSearch security API rejected the role removal") from exc


async def lookup_principal(user_client: Any) -> str:
    """Effective OpenSearch user name of the presented credential (``authinfo``)."""
    try:
        info = await user_client.transport.perform_request("GET", "/_plugins/_security/authinfo")
    except Exception as exc:
        raise RoleError("the OpenSearch user could not be determined") from exc
    name = (info or {}).get("user_name") if isinstance(info, dict) else None
    if not isinstance(name, str) or not name:
        raise RoleError("the OpenSearch user could not be determined")
    return name
