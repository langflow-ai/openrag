"""Request identity resolution for browser, upstream, and API-key auth."""

import base64
import dataclasses
import hashlib
from typing import Optional

from fastapi import HTTPException, Request

from auth.user_identity_cache import _resolve_db_user_id
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Header names whose values must never be logged verbatim. Logged as a
# redacted fingerprint (length + sha prefix) so a value can be correlated
# across hops without exposing the secret.
_SENSITIVE_HEADERS = {
    "authorization",
    "x-openrag-api-jwt",
    "x-api-key",
    "x-username",
    "cookie",
    "x-ibm-lh-credentials",
}


def _redact_header(name: str, value: str) -> str:
    """Redact a header value for logging — never emit the raw secret."""
    if not value:
        return ""
    if name.lower() in _SENSITIVE_HEADERS:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        return f"<redacted len={len(value)} sha={digest}>"
    return value


async def _attach_db_user_id(request: Request, user: User | None) -> User | None:
    """Attach the internal SQL users.id to the request user.

    `User.user_id` remains the external auth subject used in JWT/OpenSearch
    flows. `User.db_user_id` is the OpenRAG owner id used by SQL-backed
    RBAC and ownership tables.
    """
    if user is None:
        request.state.db_user_id = None
        request.state.user = None
        return None
    jwt_roles = getattr(request.state, "jwt_roles", None)
    from config.settings import is_dev_role_toggle_enabled

    if is_dev_role_toggle_enabled():
        jwt_roles = None
    db_user_id = await _resolve_db_user_id(user, jwt_roles=jwt_roles)
    user_with_db_id = dataclasses.replace(user, db_user_id=db_user_id)
    request.state.db_user_id = db_user_id
    request.state.user = user_with_db_id
    return user_with_db_id


async def _attach_opensearch_jwt(
    request: Request,
    user: User | None,
    session_manager,
    token_hint: str | None = None,
) -> User | None:
    """Attach OpenSearch auth state and refresh DLS principal lookup state."""
    if user is None:
        return None

    effective_token = session_manager.get_effective_jwt_token(
        user.user_id,
        token_hint if token_hint is not None else user.jwt_token,
    )
    if effective_token != user.jwt_token:
        user = dataclasses.replace(user, jwt_token=effective_token)

    services = getattr(getattr(request, "app", None), "state", None)
    services = getattr(services, "services", {}) or {}
    dls_principal_service = services.get("dls_principal_service")

    if dls_principal_service is not None:
        try:
            principals = await dls_principal_service.refresh_user_principals(user)
            request.state.opensearch_dls_principals = principals
        except Exception as e:
            logger.warning(
                "Failed to refresh OpenSearch DLS principals",
                user_id=user.user_id,
                error=str(e),
            )

    request.state.opensearch_group_roles = []

    return user


async def _attach_request_user(
    request: Request,
    user: User | None,
    session_manager,
    token_hint: str | None = None,
) -> User | None:
    user_with_opensearch_jwt = await _attach_opensearch_jwt(
        request,
        user,
        session_manager,
        token_hint=token_hint,
    )
    return await _attach_db_user_id(request, user_with_opensearch_jwt)


def _stage_jwt_roles(request: Request, claims: dict, user_id: str | None) -> None:
    """Extract OpenRAG roles from decoded JWT *claims* and stash them on
    ``request.state.jwt_roles`` so the subsequent ``_attach_db_user_id`` call
    syncs them to the DB.

    Behavior mirrors the ibm-openrag-session cookie path:
      * RBAC off (``jwt_roles_enabled()`` False) -> ``jwt_roles = None`` so the
        legacy default-role path runs and existing DB roles are not clobbered.
      * RBAC on -> roles are extracted; if the JWT carries no recognized
        OpenRAG role, raise HTTP 401.
    """
    from auth.jwt_roles import extract_jwt_role_names, jwt_roles_enabled

    jwt_roles: list[str] | None = None
    if jwt_roles_enabled():
        jwt_roles = extract_jwt_role_names(claims)
        if not jwt_roles:
            logger.warning(
                "JWT carries no recognized OpenRAG role claim",
                user_id=user_id,
            )
            raise HTTPException(
                status_code=401,
                detail="User has no OpenRAG roles assigned",
            )
    logger.debug(f"JWT roles: {jwt_roles}")
    request.state.jwt_roles = jwt_roles


async def _resolve_lakehouse_credentials(
    request: Request, user_id: str | None
) -> tuple[str | None, str | None]:
    """Resolve the lakehouse Basic credentials used for the user-scoped
    OpenSearch client. Shared by the session-cookie surface (``_get_ibm_user``)
    and the /v1 JWT-in-header surface (``resolve_api_key_user``).
    """
    from auth.ibm_auth import extract_ibm_credentials
    from config.settings import IBM_CREDENTIALS_HEADER

    connector_service = None
    app_state = getattr(getattr(request, "app", None), "state", None)
    services = getattr(app_state, "services", None)
    if services:
        connector_service = services.get("connector_service")

    lh_credentials = request.headers.get(IBM_CREDENTIALS_HEADER, "")
    if lh_credentials and lh_credentials.strip() != "":
        logger.debug("[AUTH] IBM LH credentials found in request headers")
        opensearch_username, _ = extract_ibm_credentials(lh_credentials)
        upsert_user_id = user_id or opensearch_username
        if connector_service and upsert_user_id:
            logger.debug("[AUTH] Upserting IBM LH credentials to connections store")
            try:
                await connector_service.connection_manager.upsert_ibm_credentials(
                    user_id=upsert_user_id,
                    basic_credentials=lh_credentials,
                    username=upsert_user_id,
                )
            except Exception as exc:  # noqa: BLE001 — persistence is best-effort
                logger.warning(
                    "[AUTH] Failed to persist IBM LH credentials to connections store",
                    user_id=upsert_user_id,
                    error=str(exc),
                )
        return opensearch_username, lh_credentials

    if connector_service and user_id:
        try:
            connections = await connector_service.connection_manager.list_connections(
                user_id=user_id, connector_type="ibm_credentials"
            )
        except Exception as exc:  # noqa: BLE001 — auth must degrade, not 500
            logger.warning(
                "[AUTH] Failed to read IBM LH credentials from connections store",
                user_id=user_id,
                error=str(exc),
            )
            connections = []
        if connections:
            lh_credentials = connections[0].config.get("basic_credentials")
            if lh_credentials and lh_credentials.strip() != "":
                logger.debug("[AUTH] IBM LH credentials found in connections store")
                opensearch_username, _ = extract_ibm_credentials(lh_credentials)
                return opensearch_username, lh_credentials

    return None, None


async def _get_ibm_user(request: Request, required: bool) -> Optional["User"]:
    """Authenticate via upstream auth.

    0. Configured credentials header containing OpenSearch credentials.
    1. Configured session cookie. When JWT-role sync is enabled, the JWT is
       instead read from the gateway-forwarded header named by ``get_jwt_auth_header()``;
       identity and roles both come from that token.
    2. Local dev basic-auth cookie.

    If *required* is True, raises HTTP 401 when none is present.
    If *required* is False, returns None instead of raising.
    """
    import auth.ibm_auth as ibm_auth
    from auth.ibm_auth import extract_ibm_credentials
    from auth.jwt_roles import jwt_roles_enabled
    from config.settings import (
        IBM_SESSION_COOKIE_NAME,
        PLATFORM_PASSWORD,
        PLATFORM_USERNAME,
        get_jwt_auth_header,
    )
    from config.utils import resolve_jwt_claims

    # ── Option -1: Environment variable override (local dev/calls) ───────

    if PLATFORM_USERNAME and PLATFORM_PASSWORD:
        logger.debug("[AUTH] Using PLATFORM_USERNAME and PLATFORM_PASSWORD from environment")
        creds = f"{PLATFORM_USERNAME}:{PLATFORM_PASSWORD}"
        lh_credentials = base64.b64encode(creds.encode()).decode()
        user = User(
            user_id=PLATFORM_USERNAME,
            email=PLATFORM_USERNAME,
            name=PLATFORM_USERNAME,
            picture=None,
            provider="ibm_ams_env",
            jwt_token=f"Basic {lh_credentials}",
            opensearch_username=PLATFORM_USERNAME,
            opensearch_credentials=lh_credentials,
        )
        request.state.user = user
        return user

    # When RBAC/JWT-role sync is on, the gateway forwards the end-user JWT in the
    # configured header; use it as the source of identity and roles. When RBAC is
    # off, preserve the existing ibm-openrag-session cookie flow.
    if jwt_roles_enabled():
        header_name = get_jwt_auth_header()
        raw_jwt = request.headers.get(header_name, "")
        logger.debug(
            "[AUTH] JWT-role header lookup",
            header_name=header_name,
            jwt_present=bool(raw_jwt and raw_jwt.strip()),
        )
        ibm_token = (
            raw_jwt[7:].strip() if raw_jwt.startswith("Bearer ") else raw_jwt.strip()
        ) or None

        claims = resolve_jwt_claims(ibm_token)
    else:
        ibm_token = request.cookies.get(IBM_SESSION_COOKIE_NAME)
        claims = None
    user_id = None
    email = None
    name = None
    # Default for the no-token / no-claims / no-sub cases; overwritten by
    # _stage_jwt_roles when a valid JWT subject is present.
    request.state.jwt_roles = None
    if ibm_token:
        if claims is None:
            logger.debug("[AUTH] IBM JWT token found in request cookies")
            claims = ibm_auth.decode_ibm_jwt(ibm_token)
        if claims is not None:
            logger.debug(
                "[AUTH] JWT claims resolved"
                if jwt_roles_enabled()
                else "[AUTH] IBM JWT claims decoded successfully"
            )
            sub = claims.get("sub")
            if not sub:
                logger.warning(
                    "IBM JWT is missing required 'sub' claim; treating as unauthenticated"
                )
            else:
                user_id = claims.get("username", sub)
                email = claims.get("username", sub)
                name = claims.get("display_name", claims.get("username", sub))
                # RBAC off -> jwt_roles stays None (legacy default-role path,
                # existing DB roles untouched). RBAC on -> extract + 401 if none.
                _stage_jwt_roles(request, claims, user_id)

    from utils.run_mode_utils import get_run_mode, is_run_mode_on_prem, is_run_mode_saas

    platform_rbac = (is_run_mode_saas() or is_run_mode_on_prem()) and jwt_roles_enabled()

    # The forwarded end-user JWT is the OpenSearch credential — OpenSearch's
    # openid_auth_domain validates it via the backend JWKS. Build it once; it's
    # used both as the platform+rbac authoritative credential and as the
    # header-less fallback in other modes.
    jwt_user = None
    if ibm_token and user_id:
        jwt_user = User(
            user_id=user_id,
            email=email,
            name=name,
            picture=None,
            provider="ibm_ams",
            jwt_token=f"Bearer {ibm_token}",
            opensearch_username=None,
            opensearch_credentials=None,
        )

    # In SaaS/on-prem + RBAC the JWT is authoritative: the lakehouse
    # `X-IBM-LH-Credentials` Basic credential must NOT override it (when the
    # gateway began injecting that header, OpenSearch rejected the Basic cred
    # with 401 and every data-plane call surfaced as a misleading 403
    # "insufficient permissions"). Return before `_resolve_lakehouse_credentials`
    # so its connections-store upsert side effect is also skipped. Mirrors the
    # /v1 surface, which already treats the JWT as primary.
    if platform_rbac:
        if jwt_user:
            logger.debug(
                "[AUTH] User created from forwarded JWT (platform+rbac; lakehouse creds bypassed)",
                run_mode=get_run_mode(),
            )
            request.state.user = jwt_user
            return jwt_user
        # SaaS/on-prem + RBAC but no valid forwarded JWT (missing header,
        # undecodable, or no `sub`). Do NOT degrade to lakehouse Basic creds or
        # the debug cookie — that would authenticate (and write DB user/role
        # rows) under a roles-less identity. Fail loud, mirroring
        # resolve_api_key_user's platform_rbac branch.
        request.state.user = None
        if required:
            logger.error(
                "[AUTH] No valid forwarded JWT under platform+RBAC; refusing lakehouse/basic fallback",
                jwt_present=bool(ibm_token),
                run_mode=get_run_mode(),
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "invalid_jwt" if ibm_token else "missing_user_jwt",
                    "message": (
                        "No valid user JWT was forwarded by the gateway. In "
                        "SaaS/on-prem RBAC mode the gateway must forward the "
                        "end-user JWT on every request."
                    ),
                },
            )
        return None

    # Other modes: lakehouse Basic creds take precedence when present.
    opensearch_username, lh_credentials = await _resolve_lakehouse_credentials(request, user_id)

    if lh_credentials:
        user_id = user_id or opensearch_username
        email = email or opensearch_username
        name = name or opensearch_username
        user = User(
            user_id=user_id,
            email=email,
            name=name,
            picture=None,
            provider="ibm_ams",
            jwt_token=f"Basic {lh_credentials}",
            opensearch_username=opensearch_username,
            opensearch_credentials=lh_credentials,
        )
        logger.debug("[AUTH] User created successfully")
        request.state.user = user
        return user

    if jwt_user:
        logger.warning(
            "[AUTH] IBM LH credentials not found in header or connections store. Using JWT token instead."
        )
        request.state.user = jwt_user
        return jwt_user

    if ibm_token and not user_id:
        logger.warning("IBM JWT cookie present but could not extract user_id from claims.")
        request.state.user = None
        return None

    auth_header = request.cookies.get("ibm-auth-basic", "")
    if auth_header.startswith("Basic "):
        logger.debug("[AUTH] Debug mode enabled, extracting IBM LH credentials from cookie")
        username, _ = extract_ibm_credentials(auth_header)
        logger.debug("[AUTH] IBM LH credentials extracted successfully")
        user = User(
            user_id=username,
            email=username,
            name=username,
            picture=None,
            provider="ibm_ams_basic",
            jwt_token=auth_header,
            opensearch_username=username,
            opensearch_credentials=auth_header,
        )
        logger.debug("[AUTH] User created successfully")
        request.state.user = user
        return user

    # ── Neither present ──────────────────────────────────────────────────
    if required:
        raise HTTPException(status_code=401, detail="IBM authentication required")
    request.state.user = None
    return None


async def resolve_current_user(request: Request, session_manager) -> User:
    """Require JWT cookie authentication and attach request identity state."""
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # Upstream cookie auth takes priority when enabled.
    if IBM_AUTH_ENABLED:
        logger.debug("[AUTH] IBM auth mode enabled, getting current user")
        user = await _get_ibm_user(request, required=True)
        if user and user.user_id and user.user_id not in session_manager.users:
            session_manager.users[user.user_id] = user
        return await _attach_request_user(request, user, session_manager)

    if is_no_auth_mode():
        user = AnonymousUser()
        return await _attach_request_user(request, user, session_manager)

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = session_manager.get_user_from_token(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _attach_request_user(
        request,
        user,
        session_manager,
        token_hint=auth_token,
    )


async def resolve_optional_user(request: Request, session_manager) -> User | None:
    """Optionally extract JWT cookie user and attach request identity state."""
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # Upstream cookie auth takes priority when enabled.
    if IBM_AUTH_ENABLED:
        logger.debug("[AUTH] IBM auth mode enabled, getting optional user")
        user = await _get_ibm_user(request, required=False)
        if user and user.user_id and user.user_id not in session_manager.users:
            session_manager.users[user.user_id] = user
        if user:
            return await _attach_request_user(request, user, session_manager)
        request.state.db_user_id = None
        return None

    if is_no_auth_mode():
        user = AnonymousUser()
        return await _attach_request_user(request, user, session_manager)

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        request.state.user = None
        return None

    user = session_manager.get_user_from_token(auth_token)
    if user:
        return await _attach_request_user(
            request,
            user,
            session_manager,
            token_hint=auth_token,
        )
    request.state.user = None
    request.state.db_user_id = None
    return None


async def resolve_api_key_user(request: Request, api_key_service, session_manager) -> User:
    """Require API key or upstream authentication and attach request identity state."""
    # ── JWT-in-header path ───────────────────────────────────────────────
    # An upstream gateway may forward the end-user's JWT in a configurable
    # header. Its signature is verified by discovering the issuer's keys from
    # the token's own `iss` claim (config.utils.verify_jwt_from_issuer); when
    # valid the JWT becomes the source of identity. Under RBAC it also supplies
    # the user's roles (synced via request.state.jwt_roles ->
    # _attach_db_user_id), with a 401 when no recognized role is present.
    from auth.jwt_roles import jwt_roles_enabled
    from config.settings import (
        IBM_AUTH_ENABLED,
        get_api_jwt_header,
        get_jwt_auth_header,
    )
    from config.utils import resolve_jwt_claims
    from utils.run_mode_utils import get_run_mode, is_run_mode_on_prem, is_run_mode_saas

    # SaaS/on-prem + RBAC: the gateway MUST forward the end-user JWT on every
    # /v1 request. When it doesn't, we must NOT silently degrade to lakehouse
    # Basic creds — that path does DB user writes under a degraded identity and
    # can clobber the shared users row the same person sees on UI login. Fail
    # loud (401) with no DB side effects instead; explicit orag_ API-key auth
    # still works.
    platform_rbac = (is_run_mode_saas() or is_run_mode_on_prem()) and jwt_roles_enabled()

    # Primary: the gateway-forwarded JWT header (default Authorization).
    # Fallback: the API/MCP add-on header — FastMCP strips Authorization before
    # proxying an MCP tool call to this /v1 handler, so MCP/API callers supply
    # the JWT in get_api_jwt_header() instead.
    jwt_header = get_jwt_auth_header()
    raw_jwt = request.headers.get(jwt_header, "")

    safe_headers = {k: _redact_header(k, v) for k, v in request.headers.items()}
    logger.debug("[AUTH] Incoming /v1 request headers (redacted)", headers=safe_headers)

    if not (raw_jwt and raw_jwt.strip()):
        jwt_header = get_api_jwt_header()
        raw_jwt = request.headers.get(jwt_header, "")
    logger.debug(
        "[AUTH] API-key path JWT header lookup",
        header_name=jwt_header,
        jwt_present=bool(raw_jwt and raw_jwt.strip()),
        jwt_preview=_redact_header(jwt_header, raw_jwt),
    )
    if raw_jwt and raw_jwt.strip():
        token = raw_jwt[7:].strip() if raw_jwt.startswith("Bearer ") else raw_jwt.strip()
        claims = resolve_jwt_claims(token)
        sub = claims.get("sub") if claims else None
        if sub:
            user = User(
                user_id=claims.get("username", sub),
                email=claims.get("username", sub),
                name=claims.get("display_name", claims.get("username", sub)),
                picture=None,
                # Same provider as the cookie path so the forwarded user
                # resolves to the SAME users row (oauth_provider, oauth_subject).
                provider="ibm_ams",
                jwt_token=f"Bearer {token}",
            )
            _stage_jwt_roles(request, claims, user.user_id)
            logger.debug(
                "[AUTH] API user authenticated via JWT",
                user_id=user.user_id,
                roles=getattr(request.state, "jwt_roles", None),
            )
            # The forwarded JWT is primary for ALL operations (identity, roles,
            # and downstream OpenSearch calls, which validate it via OIDC) —
            # same as the session surface (_get_ibm_user). NOTE (gateway
            # requirement): under RBAC this JWT is also the authoritative role
            # source. Traefik must mint it with the user's real OpenRAG role
            # claims (same as the UI session JWT), otherwise every /v1 call
            # re-syncs the user down to whatever the claim carries.
            request.state.user = user
            return await _attach_request_user(request, user, session_manager)
        if jwt_roles_enabled():
            # A JWT was asserted but failed verification/decode. Under RBAC we
            # must not silently downgrade to the API-key identity.
            logger.error(
                "[AUTH] JWT in request header failed verification/decode",
                header_name=jwt_header,
                jwt_preview=_redact_header(jwt_header, raw_jwt),
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "invalid_jwt",
                    "message": (
                        f"The JWT in the '{jwt_header}' header could not be "
                        "verified or decoded. Ensure the gateway forwards a valid, "
                        "unexpired user JWT issued by a trusted identity provider."
                    ),
                },
            )
        # RBAC off + missing/invalid JWT -> fall through to the API-key path.
    else:
        if platform_rbac:
            # In SaaS/on-prem the gateway is responsible for forwarding the
            # end-user JWT on every API/MCP request; its absence is a gateway
            # misconfiguration, not a normal client state. Fail fast here —
            # before any lakehouse / X-Username / API-key fallback — so no DB
            # user/role write ever runs under a degraded (roles-less) identity.
            logger.error(
                f"[AUTH] JWT not found in request header — run_mode={get_run_mode()} "
                "with RBAC enabled requires the gateway to forward the user JWT",
                header_name=jwt_header,
                authorization_present=bool(request.headers.get("authorization")),
                api_jwt_present=bool(request.headers.get(get_api_jwt_header())),
                seen_auth_headers={
                    k: _redact_header(k, v)
                    for k, v in request.headers.items()
                    if k.lower() in _SENSITIVE_HEADERS
                },
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "missing_user_jwt",
                    "message": (
                        "No user JWT was forwarded by the gateway. In "
                        "SaaS/on-prem RBAC mode the gateway must forward the "
                        "end-user JWT on every /v1 request."
                    ),
                },
            )
        if IBM_AUTH_ENABLED:
            # No JWT — fall back to lakehouse Basic credentials (credentials
            # header, upserted to the connections store), mirroring the
            # session surface's header branch in _get_ibm_user.
            os_username, lh_credentials = await _resolve_lakehouse_credentials(request, None)
            if lh_credentials:
                logger.info(
                    "[AUTH] Using IBM LH credentials as JWT token",
                    username=os_username,
                )
                user = User(
                    user_id=os_username,
                    email=os_username,
                    name=os_username,
                    picture=None,
                    provider="ibm_ams",
                    jwt_token=f"Basic {lh_credentials}",
                    opensearch_username=os_username,
                    opensearch_credentials=lh_credentials,
                )
                request.state.user = user
                return await _attach_request_user(request, user, session_manager)

    # Upstream auth path: X-Username + X-Api-Key sent directly by an MCP/SDK
    # client. Not the SaaS path — there, Traefik consumes these headers for
    # login and injects the JWT handled by the branch above.
    if IBM_AUTH_ENABLED:
        ibm_username = request.headers.get("X-Username")
        ibm_api_key = request.headers.get("X-Api-Key")
        if ibm_username and ibm_api_key:
            # check if ibm api key is base 64 encoded
            userpass = f"{ibm_username}:{ibm_api_key}"
            ibm_api_key_b64 = base64.b64encode(userpass.encode("utf-8")).decode("utf-8")

            user = User(
                user_id=ibm_username,
                email=ibm_username,
                name=ibm_username,
                picture=None,
                provider="ibm_ams",
                jwt_token=f"Basic {ibm_api_key_b64}",
                opensearch_username=ibm_username,
                opensearch_credentials=ibm_api_key_b64,
            )
            return await _attach_request_user(request, user, session_manager)

    # API key path
    api_key = request.headers.get("X-API-Key")
    if not api_key or not api_key.startswith("orag_"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token.startswith("orag_"):
                api_key = token

    if not api_key:
        # platform_rbac is already handled by the fail-fast 401 above (no JWT
        # -> missing_user_jwt), so reaching here means non-platform_rbac:
        # prompt for an API key as before.
        raise HTTPException(
            status_code=401,
            detail={
                "error": "API key required",
                "message": "Provide API key via X-API-Key header or Authorization: Bearer header",
            },
        )

    user_info = await api_key_service.validate_key(api_key)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Invalid API key",
                "message": "The provided API key is invalid or has been revoked",
            },
        )

    user = User(
        user_id=user_info["user_id"],
        email=user_info["user_email"],
        name=user_info.get("name", "API User"),
        picture=None,
        provider="api_key",
    )

    # Register the API key user so get_effective_jwt_token can find them
    if user.user_id not in session_manager.users:
        session_manager.users[user.user_id] = user

    request.state.api_key_id = user_info["key_id"]
    # Phase 2 will populate api_key_role_ids from the SQL api_keys table.
    # In Phase 1 we leave it unset so require_permission falls back to the
    # user's live role membership (no privilege escalation possible).
    request.state.api_key_role_ids = getattr(request.state, "api_key_role_ids", None)

    return await _attach_request_user(request, user, session_manager)
