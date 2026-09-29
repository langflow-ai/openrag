"""Shared Microsoft OAuth utilities used by both SharePoint and OneDrive connectors."""

from __future__ import annotations

from utils.logging_config import get_logger

logger = get_logger(__name__)


def _tenant_from_home_account_id(home_account_id: object) -> str | None:
    if not isinstance(home_account_id, str):
        return None
    parts = home_account_id.split(".")
    if len(parts) >= 2 and parts[-1]:
        return parts[-1]
    return None


def trusted_tenant_id_from_account(account: dict | None) -> str | None:
    """Return the Microsoft tenant id from MSAL account metadata."""
    if not account:
        return None
    realm = account.get("realm")
    if isinstance(realm, str) and realm:
        return realm
    return _tenant_from_home_account_id(account.get("home_account_id"))


def trusted_tenant_id_from_token_result(result: dict | None) -> str | None:
    """Return the Microsoft tenant id from MSAL token response metadata."""
    if not result:
        return None
    id_token_claims = result.get("id_token_claims")
    if isinstance(id_token_claims, dict):
        tid = id_token_claims.get("tid")
        if isinstance(tid, str) and tid:
            return tid
    tenant_id = result.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id:
        return tenant_id
    return None


def enforce_ms_tenant_allowlist(tenant_id: str | None) -> None:
    """Enforce OpenRAG's Microsoft tenant policy from trusted MSAL metadata."""
    from config.settings import MICROSOFT_ALLOWED_TENANT_IDS
    from utils.jwt_verification import InvalidIssuerError

    if MICROSOFT_ALLOWED_TENANT_IDS is None:
        return
    if not tenant_id:
        raise InvalidIssuerError("Microsoft tenant id is required by the configured allow-list")
    if tenant_id not in MICROSOFT_ALLOWED_TENANT_IDS:
        logger.warning("Microsoft token tenant not in allow-list", tenant_id=tenant_id)
        raise InvalidIssuerError(
            f"Tenant '{tenant_id}' is not in the configured allowed tenant list"
        )


def verify_ms_access_token(access_token: str | None, tenant_id: str | None = None) -> dict | None:
    """Handle a Microsoft access token obtained via MSAL.

    OpenRAG only forwards these bearer tokens to Microsoft Graph. Graph is the
    resource server responsible for validating Graph-audience access tokens, so
    this helper deliberately avoids decoding or using local JWT claims.
    """
    enforce_ms_tenant_allowlist(tenant_id)

    if not access_token:
        return None

    raw_token = access_token.removeprefix("Bearer ").strip()
    if raw_token.count(".") != 2:
        logger.debug("Microsoft access token is opaque (non-JWT)")
        return None

    logger.debug(
        "Microsoft access token is a JWT for an external resource; "
        "leaving validation to Microsoft Graph",
        tenant_hint=tenant_id,
    )
    return None
