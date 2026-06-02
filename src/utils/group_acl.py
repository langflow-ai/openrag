"""Helpers for compact connector group ACL role names."""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from collections.abc import Iterable
from typing import Any

_SAFE_COMPONENT_RE = re.compile(r"^[a-z0-9_-]+$")


def compact_acl_component(value: object, *, max_length: int = 48) -> str:
    """Return a short, role-safe component for provider/tenant/group IDs."""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("ACL role component cannot be empty")

    try:
        parsed_uuid = uuid.UUID(text)
    except ValueError:
        if _SAFE_COMPONENT_RE.fullmatch(text) and len(text) <= max_length:
            return text
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return "h" + base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode("ascii")

    return base64.urlsafe_b64encode(parsed_uuid.bytes).rstrip(b"=").decode("ascii")


def canonical_group_role(provider_code: str, tenant_id: object, group_id: object) -> str:
    """Build the OpenSearch backend role used for connector group ACLs."""
    provider = compact_acl_component(provider_code, max_length=16)
    tenant = compact_acl_component(tenant_id or "global")
    group = compact_acl_component(group_id)
    return f"g:{provider}:{tenant}:{group}"


def canonical_user_principal(provider_code: str, tenant_id: object, user_id: object) -> str:
    """Build the provider-scoped principal used for connector user ACLs."""
    provider = compact_acl_component(provider_code, max_length=16)
    tenant = compact_acl_component(tenant_id or "global")
    user = compact_acl_component(user_id)
    return f"u:{provider}:{tenant}:{user}"


def canonical_group_roles(
    provider_code: str,
    tenant_id: object,
    group_ids: Iterable[object],
) -> list[str]:
    """Canonicalize and deduplicate group IDs while preserving first-seen order."""
    roles: list[str] = []
    seen: set[str] = set()
    for group_id in group_ids or ():
        try:
            role = canonical_group_role(provider_code, tenant_id, group_id)
        except ValueError:
            continue
        if role not in seen:
            seen.add(role)
            roles.append(role)
    return roles


def canonical_user_principals(
    provider_code: str,
    tenant_id: object,
    user_ids: Iterable[object],
) -> list[str]:
    """Canonicalize and deduplicate user IDs while preserving first-seen order."""
    principals: list[str] = []
    seen: set[str] = set()
    for user_id in user_ids or ():
        try:
            principal = canonical_user_principal(provider_code, tenant_id, user_id)
        except ValueError:
            continue
        if principal not in seen:
            seen.add(principal)
            principals.append(principal)
    return principals


def unique_acl_principals(principals: Iterable[object]) -> list[str]:
    """Return non-empty ACL principals without duplicates, preserving order."""
    unique: list[str] = []
    seen: set[str] = set()
    for principal in principals or ():
        value = str(principal or "").strip()
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def acl_principal_label(
    principal: object,
    *,
    kind: str,
    provider: str,
    display_name: object = None,
    email: object = None,
    external_id: object = None,
) -> dict[str, Any] | None:
    """Build non-authoritative display metadata for an ACL principal."""
    principal_value = str(principal or "").strip()
    if not principal_value:
        return None

    label: dict[str, Any] = {
        "principal": principal_value,
        "kind": str(kind or "").strip() or "unknown",
        "provider": str(provider or "").strip() or "unknown",
    }
    for key, value in (
        ("display_name", display_name),
        ("email", email),
        ("external_id", external_id),
    ):
        if value is None:
            continue
        value_text = str(value).strip()
        if value_text:
            label[key] = value_text
    return label


def unique_acl_principal_labels(labels: Iterable[object]) -> list[dict[str, Any]]:
    """Return display labels keyed by canonical principal, preserving first-seen order."""
    unique: list[dict[str, Any]] = []
    by_principal: dict[str, dict[str, Any]] = {}

    for raw_label in labels or ():
        if not isinstance(raw_label, dict):
            continue
        principal = str(raw_label.get("principal") or "").strip()
        if not principal:
            continue

        label: dict[str, Any] = {"principal": principal}
        for key in ("kind", "provider", "display_name", "email", "external_id"):
            value = raw_label.get(key)
            if value is None:
                continue
            value_text = str(value).strip()
            if value_text:
                label[key] = value_text

        existing = by_principal.get(principal)
        if existing is None:
            by_principal[principal] = label
            unique.append(label)
            continue

        for key, value in label.items():
            if key not in existing and value:
                existing[key] = value

    return unique
