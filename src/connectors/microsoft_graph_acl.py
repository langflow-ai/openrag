"""Microsoft Graph group ACL helpers shared by Microsoft connectors."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import jwt

from utils.group_acl import (
    acl_principal_label,
    canonical_group_role,
    canonical_group_roles,
    canonical_user_principal,
    unique_acl_principal_labels,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

MICROSOFT_GRAPH_GROUP_PROVIDER = "m365"


def tenant_id_from_access_token(access_token: str | None, fallback: str | None = None) -> str:
    """Read the tenant id from a Microsoft access token without validating it."""
    if access_token:
        raw_token = access_token.removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(
                raw_token,
                options={"verify_signature": False, "verify_aud": False},
            )
            token_tenant = claims.get("tid")
            if token_tenant:
                return token_tenant
        except Exception as e:
            logger.debug("Could not decode Microsoft access token tenant", error=str(e))
    return fallback or "common"


def microsoft_group_role(
    group_id: str | None,
    *,
    access_token: str | None = None,
    tenant_id: str | None = None,
) -> str | None:
    """Return the canonical OpenSearch role for a Microsoft group id."""
    if not group_id:
        return None
    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    return canonical_group_role(
        MICROSOFT_GRAPH_GROUP_PROVIDER,
        resolved_tenant,
        group_id,
    )


def microsoft_user_principal(
    user_identifier: str | None,
    *,
    access_token: str | None = None,
    tenant_id: str | None = None,
) -> str | None:
    """Return the canonical DLS principal for a Microsoft Graph user identity."""
    if not user_identifier:
        return None
    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    return canonical_user_principal(
        MICROSOFT_GRAPH_GROUP_PROVIDER,
        resolved_tenant,
        user_identifier,
    )


def microsoft_group_principal_label(
    group_id: str | None,
    *,
    access_token: str | None = None,
    tenant_id: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
) -> dict[str, Any] | None:
    """Return non-authoritative display metadata for a Microsoft group principal."""
    principal = microsoft_group_role(
        group_id,
        access_token=access_token,
        tenant_id=tenant_id,
    )
    return acl_principal_label(
        principal,
        kind="group",
        provider=MICROSOFT_GRAPH_GROUP_PROVIDER,
        display_name=display_name or email or group_id,
        email=email,
        external_id=group_id,
    )


def microsoft_user_principal_label(
    user_identifier: str | None,
    *,
    access_token: str | None = None,
    tenant_id: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any] | None:
    """Return non-authoritative display metadata for a Microsoft user principal."""
    principal = microsoft_user_principal(
        user_identifier,
        access_token=access_token,
        tenant_id=tenant_id,
    )
    return acl_principal_label(
        principal,
        kind="user",
        provider=MICROSOFT_GRAPH_GROUP_PROVIDER,
        display_name=display_name or email or user_identifier,
        email=email,
        external_id=external_id or user_identifier,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def get_oauth_access_token(oauth: Any) -> str | None:
    """Return an access token string from either old dict or current string APIs."""
    if oauth is None:
        return None
    token_value = await _maybe_await(oauth.get_access_token())
    if isinstance(token_value, dict):
        return token_value.get("access_token")
    if isinstance(token_value, str):
        return token_value.removeprefix("Bearer ").strip()
    return None


async def get_current_user_microsoft_group_roles(
    oauth: Any,
    graph_base_url: str,
    *,
    tenant_id: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Fetch transitive Microsoft group memberships for the current OAuth user."""
    if oauth is None:
        return []

    try:
        access_token = await get_oauth_access_token(oauth)
    except Exception as e:
        logger.warning("Unable to get Microsoft Graph token for group ACLs", error=str(e))
        return []

    if not access_token:
        return []

    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{graph_base_url}/me/transitiveMemberOf/microsoft.graph.group"
    params: dict[str, str] | None = {"$select": "id"}
    group_ids: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            while url:
                response = await client.get(url, headers=headers, params=params)
                params = None
                if response.status_code in (401, 403):
                    logger.warning(
                        "Microsoft Graph group ACL lookup denied",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    return []
                if response.status_code != 200:
                    logger.warning(
                        "Microsoft Graph group ACL lookup failed",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    return []

                data = response.json()
                for entry in data.get("value", []):
                    group_id = entry.get("id")
                    if group_id:
                        group_ids.append(group_id)
                url = data.get("@odata.nextLink")
    except Exception as e:
        logger.warning("Microsoft Graph group ACL lookup errored", error=str(e))
        return []

    return canonical_group_roles(
        MICROSOFT_GRAPH_GROUP_PROVIDER,
        resolved_tenant,
        group_ids,
    )


def _decode_microsoft_user_identifiers(access_token: str, tenant_id: str | None) -> list[str]:
    raw_token = access_token.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(
            raw_token,
            options={"verify_signature": False, "verify_aud": False},
        )
    except Exception as e:
        logger.debug("Could not decode Microsoft access token user identifiers", error=str(e))
        return []

    identifiers: list[str] = []
    for claim in ("oid", "preferred_username", "upn", "email", "unique_name"):
        value = claims.get(claim)
        if value:
            identifiers.append(str(value))

    # If tenant_id was not in the access token, the principal helper will use
    # this fallback. Returning identifiers here keeps JWT-only aliases useful
    # even if /me is unavailable.
    if tenant_id and claims.get("sub"):
        identifiers.append(str(claims["sub"]))
    return identifiers


async def get_current_user_microsoft_principals(
    oauth: Any,
    graph_base_url: str,
    *,
    tenant_id: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Fetch canonical Microsoft user principals for the current OAuth user."""
    if oauth is None:
        return []

    try:
        access_token = await get_oauth_access_token(oauth)
    except Exception as e:
        logger.warning("Unable to get Microsoft Graph token for user ACL aliases", error=str(e))
        return []

    if not access_token:
        return []

    identifiers = _decode_microsoft_user_identifiers(access_token, tenant_id)
    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)

    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{graph_base_url}/me"
    params = {"$select": "id,userPrincipalName,mail"}

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            for key in ("id", "userPrincipalName", "mail"):
                value = data.get(key)
                if value:
                    identifiers.append(str(value))
        elif response.status_code in (401, 403):
            logger.warning(
                "Microsoft Graph user ACL alias lookup denied",
                status_code=response.status_code,
                response_text=response.text[:500],
            )
        else:
            logger.warning(
                "Microsoft Graph user ACL alias lookup failed",
                status_code=response.status_code,
                response_text=response.text[:500],
            )
    except Exception as e:
        logger.warning("Microsoft Graph user ACL alias lookup errored", error=str(e))

    principals: list[str] = []
    seen: set[str] = set()
    for identifier in identifiers:
        principal = microsoft_user_principal(
            identifier,
            access_token=access_token,
            tenant_id=resolved_tenant,
        )
        if principal and principal not in seen:
            seen.add(principal)
            principals.append(principal)
    return principals


async def get_current_user_microsoft_principal_labels(
    oauth: Any,
    graph_base_url: str,
    *,
    tenant_id: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """Fetch display labels for current Microsoft user and group principals."""
    if oauth is None:
        return []

    try:
        access_token = await get_oauth_access_token(oauth)
    except Exception as e:
        logger.warning("Unable to get Microsoft Graph token for principal labels", error=str(e))
        return []

    if not access_token:
        return []

    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    identifiers = _decode_microsoft_user_identifiers(access_token, tenant_id)
    labels: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(
                f"{graph_base_url}/me",
                headers=headers,
                params={"$select": "id,displayName,userPrincipalName,mail"},
            )
            if response.status_code == 200:
                data = response.json()
                user_email = data.get("mail") or data.get("userPrincipalName")
                for key in ("id", "userPrincipalName", "mail"):
                    value = data.get(key)
                    if value:
                        identifiers.append(str(value))
                for identifier in identifiers:
                    label = microsoft_user_principal_label(
                        identifier,
                        access_token=access_token,
                        tenant_id=resolved_tenant,
                        display_name=data.get("displayName") or user_email,
                        email=user_email,
                        external_id=identifier,
                    )
                    if label:
                        labels.append(label)
            elif response.status_code in (401, 403):
                logger.warning(
                    "Microsoft Graph user principal label lookup denied",
                    status_code=response.status_code,
                    response_text=response.text[:500],
                )
            else:
                logger.warning(
                    "Microsoft Graph user principal label lookup failed",
                    status_code=response.status_code,
                    response_text=response.text[:500],
                )

            group_url = f"{graph_base_url}/me/transitiveMemberOf/microsoft.graph.group"
            params: dict[str, str] | None = {"$select": "id,displayName,mail"}
            while group_url:
                response = await client.get(group_url, headers=headers, params=params)
                params = None
                if response.status_code in (401, 403):
                    logger.warning(
                        "Microsoft Graph group principal label lookup denied",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    break
                if response.status_code != 200:
                    logger.warning(
                        "Microsoft Graph group principal label lookup failed",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    break

                data = response.json()
                for entry in data.get("value", []):
                    group_id = entry.get("id")
                    label = microsoft_group_principal_label(
                        group_id,
                        access_token=access_token,
                        tenant_id=resolved_tenant,
                        display_name=entry.get("displayName") or entry.get("mail"),
                        email=entry.get("mail"),
                    )
                    if label:
                        labels.append(label)
                group_url = data.get("@odata.nextLink")
    except Exception as e:
        logger.warning("Microsoft Graph principal label lookup errored", error=str(e))

    return unique_acl_principal_labels(labels)
