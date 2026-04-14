from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from utils.telemetry import TelemetryClient, Category, MessageId
from utils.version_utils import OPENRAG_VERSION

from dependencies import (
    get_auth_service,
    get_optional_user,
    get_current_user,
)
from pydantic import BaseModel
from session_manager import User


class AuthInitBody(BaseModel):
    connector_type: str
    purpose: str = "data_source"
    name: Optional[str] = None
    redirect_uri: Optional[str] = None




class AuthCallbackBody(BaseModel):
    connection_id: str
    authorization_code: str
    state: str


class TokenIntrospectBody(BaseModel):
    token: str


async def auth_init(
    body: AuthInitBody,
    request: Request,
    auth_service=Depends(get_auth_service),
    user: Optional[User] = Depends(get_optional_user),
):
    """Initialize OAuth flow for authentication or data source connection"""
    try:
        connection_name = body.name or f"{body.connector_type}_{body.purpose}"
        user_id = user.user_id if user else None

        result = await auth_service.init_oauth(
            body.connector_type, body.purpose, connection_name, body.redirect_uri, user_id
        )
        return JSONResponse(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return JSONResponse(
            {"error": f"Failed to initialize OAuth: {str(e)}"}, status_code=500
        )


async def auth_callback(
    body: AuthCallbackBody,
    request: Request,
    auth_service=Depends(get_auth_service),
):
    """Handle OAuth callback - exchange authorization code for tokens"""
    try:
        result = await auth_service.handle_oauth_callback(
            body.connection_id, body.authorization_code, body.state, request
        )

        await TelemetryClient.send_event(Category.AUTHENTICATION, MessageId.ORB_AUTH_OAUTH_CALLBACK)

        # If this is app auth, set JWT cookie
        if result.get("purpose") == "app_auth" and result.get("jwt_token"):
            await TelemetryClient.send_event(Category.AUTHENTICATION, MessageId.ORB_AUTH_SUCCESS)
            response = JSONResponse(
                {k: v for k, v in result.items() if k != "jwt_token"}
            )
            response.set_cookie(
                key="auth_token",
                value=result["jwt_token"],
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=7 * 24 * 60 * 60,  # 7 days
            )
            return response
        else:
            return JSONResponse(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        await TelemetryClient.send_event(Category.AUTHENTICATION, MessageId.ORB_AUTH_OAUTH_FAILED)
        return JSONResponse({"error": f"Callback failed: {str(e)}"}, status_code=500)


async def auth_me(
    request: Request,
    auth_service=Depends(get_auth_service),
    user: Optional[User] = Depends(get_optional_user),
):
    """Get current user information"""
    result = await auth_service.get_user_info(request)
    result["version"] = OPENRAG_VERSION
    return JSONResponse(result)


async def auth_logout(
    auth_service=Depends(get_auth_service),
    user: User = Depends(get_current_user),
):
    """Logout user by clearing auth cookie(s)"""
    from config.settings import IBM_AUTH_ENABLED, IBM_SESSION_COOKIE_NAME

    await TelemetryClient.send_event(Category.AUTHENTICATION, MessageId.ORB_AUTH_LOGOUT)

    if IBM_AUTH_ENABLED:
        # Best-effort: clear cookies from the browser, but warn that the
        # server-side AMS session is NOT terminated. The IBM session cookie
        # is owned by Traefik/AMS — it may be re-injected on the next
        # proxied request if AMS still considers the session active.
        response = JSONResponse(
            {
                "status": "partial_logout",
                "message": "Browser cookies cleared, but the IBM session is "
                "managed by the identity provider and may still be active. "
                "Please log out through IBM Watsonx Data for full session termination.",
            }
        )
        response.delete_cookie(key=IBM_SESSION_COOKIE_NAME, httponly=True, samesite="lax")
        response.delete_cookie(key="ibm-auth-basic", httponly=True, samesite="lax")
        return response

    response = JSONResponse(
        {"status": "logged_out", "message": "Successfully logged out"}
    )

    # Clear the auth cookie
    response.delete_cookie(
        key="auth_token", httponly=True, secure=False, samesite="lax"
    )

    return response


async def ibm_login(request: Request):
    """IBM login endpoint.

    Production: Traefik intercepts the request, validates Basic credentials
    with AMS, and sets the ibm-openrag-session cookie before forwarding here.
    This handler just returns 200 — no cookie work needed.

    Local dev (no Traefik): stores the Basic Auth header in ibm-auth-basic
    cookie so subsequent requests can be authenticated by _get_ibm_user.
    """
    from config.settings import IBM_AUTH_ENABLED, IBM_SESSION_COOKIE_NAME

    if not IBM_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="IBM auth is not enabled")

    response = JSONResponse({"status": "ok"})

    # Local dev fallback only — in production Traefik sets the session cookie.
    if not request.cookies.get(IBM_SESSION_COOKIE_NAME):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            # secure =True not needed for local development
            response.set_cookie(
                "ibm-auth-basic",
                auth_header,
                httponly=True,
                samesite="lax",
            )

    return response
