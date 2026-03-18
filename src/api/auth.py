from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from utils.telemetry import TelemetryClient, Category, MessageId

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
    return JSONResponse(result)


async def auth_logout(
    auth_service=Depends(get_auth_service),
    user: User = Depends(get_current_user),
):
    """Logout user by clearing auth cookie"""
    await TelemetryClient.send_event(Category.AUTHENTICATION, MessageId.ORB_AUTH_LOGOUT)
    response = JSONResponse(
        {"status": "logged_out", "message": "Successfully logged out"}
    )

    # Clear the auth cookie
    response.delete_cookie(
        key="auth_token", httponly=True, secure=False, samesite="lax"
    )

    return response
