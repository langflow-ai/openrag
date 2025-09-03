from starlette.requests import Request
from starlette.responses import JSONResponse
import json
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


async def oidc_discovery(request: Request, session_manager):
    """OIDC discovery endpoint"""
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
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "auth_time",
            "email",
            "email_verified",
            "name",
            "preferred_username",
        ],
    }

    return JSONResponse(discovery_config)


async def jwks_endpoint(request: Request, session_manager):
    """JSON Web Key Set endpoint"""
    try:
        # Get the public key from session manager
        public_key_pem = session_manager.public_key_pem

        # Parse the PEM to extract key components
        public_key = serialization.load_pem_public_key(public_key_pem.encode())

        # Convert RSA components to base64url
        def int_to_base64url(value):
            # Convert integer to bytes, then to base64url
            byte_length = (value.bit_length() + 7) // 8
            value_bytes = value.to_bytes(byte_length, byteorder="big")
            return base64.urlsafe_b64encode(value_bytes).decode("ascii").rstrip("=")

        # Get public key components
        public_numbers = public_key.public_numbers()

        jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "openrag-key-1",
            "n": int_to_base64url(public_numbers.n),
            "e": int_to_base64url(public_numbers.e),
        }

        jwks = {"keys": [jwk]}

        return JSONResponse(jwks)

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to generate JWKS: {str(e)}"}, status_code=500
        )


async def token_introspection(request: Request, session_manager):
    """Token introspection endpoint (optional)"""
    try:
        data = await request.json()
        token = data.get("token")

        if not token:
            return JSONResponse({"active": False})

        # Verify the token
        payload = session_manager.verify_token(token)

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
