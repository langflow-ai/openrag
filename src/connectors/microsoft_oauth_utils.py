"""Shared Microsoft OAuth utilities used by both SharePoint and OneDrive connectors."""

from __future__ import annotations

from utils.logging_config import get_logger

logger = get_logger(__name__)


def verify_ms_access_token(access_token: str | None, tenant_id: str | None = None) -> dict | None:
    """Handle a Microsoft access token obtained via MSAL.

    OpenRAG only forwards these bearer tokens to Microsoft Graph. Graph is the
    resource server responsible for validating Graph-audience access tokens, so
    this helper deliberately avoids decoding or using local JWT claims.
    """
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
