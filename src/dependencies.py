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

import dataclasses
from typing import Optional

from fastapi import Depends, HTTPException, Request

from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


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


def get_langflow_file_service(services: dict = Depends(get_services)):
    return services["langflow_file_service"]


def get_models_service(services: dict = Depends(get_services)):
    return services["models_service"]


def get_api_key_service(services: dict = Depends(get_services)):
    return services["api_key_service"]


def get_flows_service(services: dict = Depends(get_services)):
    return services["flows_service"]


# ─────────────────────────────────────────────
# IBM AMS authentication helper
# ─────────────────────────────────────────────


async def _get_ibm_user(request: Request, required: bool) -> Optional["User"]:
    """Authenticate via IBM AMS.

    0. X-IBM-LH-Credentials header (configurable via IBM_CREDENTIALS_HEADER) —
       injected by Traefik on every forwarded request. Contains Basic credentials
       for OpenSearch. Decoded and persisted to connections.json per user.
    1. ibm-openrag-session cookie — set by Traefik after validating credentials
       with AMS. JWT is decoded without re-validation (Traefik already validated).
    2. ibm-auth-basic cookie — local dev fallback set by our ibm_login endpoint
       when Traefik is not present.

    If *required* is True, raises HTTP 401 when none is present.
    If *required* is False, returns None instead of raising.
    """
    import auth.ibm_auth as ibm_auth
    from auth.ibm_auth import extract_ibm_credentials
    from config.settings import IBM_SESSION_COOKIE_NAME, IBM_CREDENTIALS_HEADER

    # ── Option 0: Configurable credentials header (Traefik production) ───

    lh_credentials = request.headers.get(IBM_CREDENTIALS_HEADER, "")
    ibm_token = request.cookies.get(IBM_SESSION_COOKIE_NAME)
    user_id = None
    email = None
    name = None
    if ibm_token:
        logger.debug("[IBM Auth] IBM JWT token found in request cookies")
        claims = ibm_auth.decode_ibm_jwt(ibm_token)
        if claims is not None:
            logger.debug("[IBM Auth] IBM JWT claims decoded successfully")
            sub = claims.get("sub")
            if not sub:
                logger.warning("IBM JWT is missing required 'sub' claim; treating as unauthenticated")
            else:
                user_id = claims.get("username", sub)
                email = claims.get("username", sub)
                name = claims.get("display_name", claims.get("username", sub))


    if lh_credentials and lh_credentials.strip() != "":
        logger.debug("[IBM Auth] IBM LH credentials found in request headers")
        opensearch_username, _ = extract_ibm_credentials(lh_credentials)
        logger.debug("[IBM Auth] IBM LH credentials extracted successfully")

        # Persist credentials to connections.json for reuse by background processes
        connector_service = request.app.state.services.get("connector_service")
        if connector_service and user_id:
            logger.debug("[IBM Auth] Upserting IBM LH credentials to connections.json")
            await connector_service.connection_manager.upsert_ibm_credentials(
                user_id=user_id,
                basic_credentials=lh_credentials,
                username=user_id,
            )
            logger.debug("[IBM Auth] IBM LH credentials upserted successfully")

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
        logger.debug("[IBM Auth] User created successfully")
        request.state.user = user
        return user

    # ── Option 1: ibm-openrag-session cookie (production via Traefik) ───
    # ibm_token = request.cookies.get(IBM_SESSION_COOKIE_NAME)
    if ibm_token and user_id:
        logger.debug("[IBM Auth] IBM JWT cookie present and user_id found")
        logger.debug("[IBM Auth] LH credentials not available in header, reading from connections.json")
        # lh credentials not available in header, read from connections service
        connector_service = request.app.state.services.get("connector_service")
        if connector_service:
            connections = await connector_service.connection_manager.list_connections(
                user_id=user_id, connector_type="ibm_credentials"
            )
            if connections:
                lh_credentials = connections[0].config.get("basic_credentials")
        opensearch_username = None
        opensearch_credentials = None
        jwt_token = f"Bearer {ibm_token}"
        if lh_credentials and lh_credentials.strip() != "":
            logger.debug("[IBM Auth] IBM LH credentials found in connections.json")
            opensearch_username, _ = extract_ibm_credentials(lh_credentials)
            logger.debug("[IBM Auth] IBM LH credentials extracted successfully")
            opensearch_credentials = lh_credentials
            logger.debug("[IBM Auth] IBM LH credentials set successfully")
            jwt_token = f"Basic {lh_credentials}"
        else:
            logger.warning("[IBM Auth] IBM LH credentials not found in header or connections store. Using JWT token instead.")
        user = User(
            user_id=user_id,
            email=email,
            name=name,
            picture=None,
            provider="ibm_ams",
            jwt_token=jwt_token,
            opensearch_username=opensearch_username,
            opensearch_credentials=opensearch_credentials,
        )
        logger.debug("[IBM Auth] User created successfully")
        request.state.user = user
        return user

    if ibm_token and not user_id:
        logger.warning("IBM JWT cookie present but could not extract user_id from claims.")
        request.state.user = None
        return None

    # ── Option 2: ibm-auth-basic cookie (local dev, no Traefik) ─────────
    auth_header = request.cookies.get("ibm-auth-basic", "")
    if auth_header.startswith("Basic "):
        logger.debug("[IBM Auth] Debug mode enabled, extracting IBM LH credentials from cookie")
        username, _ = extract_ibm_credentials(auth_header)
        logger.debug("[IBM Auth] IBM LH credentials extracted successfully")
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
        logger.debug("[IBM Auth] User created successfully")
        request.state.user = user
        return user

    # ── Neither present ──────────────────────────────────────────────────
    if required:
        raise HTTPException(status_code=401, detail="IBM authentication required")
    request.state.user = None
    return None


# ─────────────────────────────────────────────
# Authentication dependencies
# ─────────────────────────────────────────────


async def get_current_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> User:
    """
    Require JWT cookie authentication.

    Sets request.state.user.
    Raises HTTP 401 if the user is not authenticated.
    """
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # IBM AMS cookie auth takes priority when enabled
    if IBM_AUTH_ENABLED:
        logger.debug("[IBM Auth] IBM auth mode enabled, getting current user")
        user = await _get_ibm_user(request, required=True)
        if user and user.user_id and user.user_id not in session_manager.users:
            session_manager.users[user.user_id] = user
        return user

    if is_no_auth_mode():
        user = AnonymousUser()
        request.state.user = user
        effective_token = session_manager.get_effective_jwt_token(None, None)
        user_with_token = dataclasses.replace(user, jwt_token=effective_token)
        return user_with_token

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = session_manager.get_user_from_token(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # get_effective_jwt_token handles anonymous JWT creation if needed
    effective_token = session_manager.get_effective_jwt_token(user.user_id, auth_token)
    user_with_token = dataclasses.replace(user, jwt_token=effective_token)

    request.state.user = user_with_token
    return user_with_token


async def get_optional_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> Optional[User]:
    """
    Optionally extract JWT cookie user.

    Sets request.state.user (may be None).
    Never raises — returns None if unauthenticated.
    """
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # IBM AMS cookie auth takes priority when enabled
    if IBM_AUTH_ENABLED:
        logger.debug("[IBM Auth] IBM auth mode enabled, getting optional user")
        user = await _get_ibm_user(request, required=False)
        if user and user.user_id and user.user_id not in session_manager.users:
            session_manager.users[user.user_id] = user
        return user

    if is_no_auth_mode():
        user = AnonymousUser()
        request.state.user = user
        effective_token = session_manager.get_effective_jwt_token(None, None)
        user_with_token = dataclasses.replace(user, jwt_token=effective_token)
        return user_with_token

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        request.state.user = None
        return None

    user = session_manager.get_user_from_token(auth_token)
    # get_effective_jwt_token handles anonymous JWT creation if needed
    effective_token = (
        session_manager.get_effective_jwt_token(user.user_id, auth_token)
        if user
        else None
    )
    user_with_token = (
        dataclasses.replace(user, jwt_token=effective_token) if user else None
    )

    request.state.user = user_with_token
    return user_with_token


async def get_api_key_user_async(
    request: Request,
    api_key_service=Depends(get_api_key_service),
    session_manager=Depends(get_session_manager),
) -> User:
    """
    Async dependency: require API key or IBM authentication.

    Accepts:
      - X-API-Key: orag_... header
      - Authorization: Bearer orag_... header
      - X-Username + X-Api-Key headers (when IBM_AUTH_ENABLED)

    Raises HTTP 401 if no valid credentials are provided.
    """
    from config.settings import IBM_AUTH_ENABLED

    # IBM auth path: X-Username + X-Api-Key forwarded by the MCP via the SDK
    if IBM_AUTH_ENABLED:
        ibm_username = request.headers.get("X-Username")
        ibm_api_key = request.headers.get("X-Api-Key")
        if ibm_username and ibm_api_key:
            user = User(
                user_id=ibm_username,
                email=ibm_username,
                name=ibm_username,
                picture=None,
                provider="ibm_ams",
                jwt_token=None,
                opensearch_username=ibm_username,
                opensearch_credentials=ibm_api_key,
            )
            request.state.user = user
            return user

    # API key path
    api_key = request.headers.get("X-API-Key")
    if not api_key or not api_key.startswith("orag_"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token.startswith("orag_"):
                api_key = token

    if not api_key:
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

    effective_token = session_manager.get_effective_jwt_token(user.user_id, None)
    user_with_token = dataclasses.replace(user, jwt_token=effective_token)

    request.state.user = user_with_token
    request.state.api_key_id = user_info["key_id"]

    return user_with_token
