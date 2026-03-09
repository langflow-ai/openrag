import os

from fastapi import Depends, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
import base64
from cryptography.hazmat.primitives import serialization

from dependencies import get_session_manager


class TokenIntrospectBody(BaseModel):
    token: str


async def oidc_discovery(
    request: Request,
    session_manager=Depends(get_session_manager),
):
    """OIDC discovery endpoint"""
    openrag_fqdn = os.getenv("OPENRAG_FQDN")
    if openrag_fqdn:
        base_url = f"http://{openrag_fqdn}:8000"
    else:
        base_url = str(request.base_url).rstrip("/")

    discovery_config = {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/auth/init",
        "token_endpoint": f"{base_url}/auth/callback",
        "jwks_uri": f"{base_url}/auth/jwks",
        "userinfo_endpoint": f"{base_url}/auth/me",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "email", "profile"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "auth_time",
            "email", "email_verified", "name", "preferred_username",
        ],
    }

    return JSONResponse(discovery_config)


async def jwks_endpoint(
    session_manager=Depends(get_session_manager),
):
    """JSON Web Key Set endpoint"""
    try:
        public_key_pem = session_manager.public_key_pem

        if public_key_pem is None:
            return JSONResponse({"keys": []})

        public_key = serialization.load_pem_public_key(public_key_pem.encode())

        def int_to_base64url(value):
            byte_length = (value.bit_length() + 7) // 8
            value_bytes = value.to_bytes(byte_length, byteorder="big")
            return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

        public_numbers = public_key.public_numbers()

        jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "openrag-key-1",
            "n": int_to_base64url(public_numbers.n),
            "e": int_to_base64url(public_numbers.e),
        }

        return JSONResponse({"keys": [jwk]})

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to generate JWKS: {str(e)}"}, status_code=500
        )


async def token_introspection(
    body: TokenIntrospectBody,
    session_manager=Depends(get_session_manager),
):
    """Token introspection endpoint"""
    try:
        payload = session_manager.verify_token(body.token)

        if payload:
            return JSONResponse(
                {
                    "active": True,
                    "sub": payload.get("sub"),
                    "aud": payload.get("aud"),
                    "iss": payload.get("iss"),
                    "exp": payload.get("exp"),
                    "iat": payload.get("iat"),
                    "email": payload.get("email"),
                    "name": payload.get("name"),
                    "preferred_username": payload.get("preferred_username"),
                }
            )
        else:
            return JSONResponse({"active": False})

    except Exception as e:
        return JSONResponse(
            {"error": f"Token introspection failed: {str(e)}"}, status_code=500
        )
