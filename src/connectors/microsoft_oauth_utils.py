"""Shared Microsoft OAuth utilities used by both SharePoint and OneDrive connectors."""

from __future__ import annotations

import jwt

from utils.logging_config import get_logger

logger = get_logger(__name__)


def verify_ms_access_token(access_token: str | None, tenant_id: str | None = None) -> dict | None:
    """Verify a Microsoft access token obtained via MSAL.

    Returns the verified claims dict on success.
    Returns None when no token is present, verification is not configured, or the
    token is opaque (not a JWT) — MSAL sometimes issues opaque tokens for Graph
    resources; those are trusted by virtue of the confidential-client OAuth flow.
    Raises JWTVerificationError (or a subclass) when the token IS a JWT but fails
    signature, expiry, audience, or issuer validation.
    """
    if not access_token:
        return None

    raw_token = access_token.removeprefix("Bearer ").strip()

    # MSAL can return opaque (non-JWT) tokens for some resources (e.g. Graph).
    # PyJWT raises DecodeError("Not enough segments") for these — they are trusted
    # by the confidential-client OAuth flow, so skip verification silently.
    try:
        jwt.get_unverified_header(raw_token)
    except jwt.DecodeError:
        logger.debug("Microsoft access token is opaque (non-JWT) — skipping verification")
        return None

    from config.settings import MICROSOFT_ALLOWED_TENANT_IDS, MICROSOFT_GRAPH_OAUTH_CLIENT_ID
    from utils.jwt_verification import verify_microsoft_access_token

    if not MICROSOFT_GRAPH_OAUTH_CLIENT_ID:
        logger.warning(
            "MICROSOFT_GRAPH_OAUTH_CLIENT_ID not configured - skipping access token verification"
        )
        return None

    # Raises JWTVerificationError on any failure — intentionally not caught here
    # so that callers propagate the error and refuse to return an unverified token.
    claims = verify_microsoft_access_token(
        raw_token,
        MICROSOFT_GRAPH_OAUTH_CLIENT_ID,
        tenant_id=tenant_id,
        allowed_tenant_ids=MICROSOFT_ALLOWED_TENANT_IDS,
    )
    logger.debug("Microsoft access token verified", tenant=claims.get("tid"))
    return claims
