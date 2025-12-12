import json
import jwt
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from cryptography.hazmat.primitives import serialization
import os
from utils.logging_config import get_logger

logger = get_logger(__name__)

from utils.logging_config import get_logger

logger = get_logger(__name__)
@dataclass
class User:
    """User information from OAuth provider"""

    user_id: str  # From OAuth sub claim
    email: str
    name: str
    picture: str = None
    provider: str = "google"
    created_at: datetime = None
    last_login: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_login is None:
            self.last_login = datetime.now()

class AnonymousUser(User):
    """Anonymous user"""

    def __init__(self):
        super().__init__(
            user_id="anonymous",
            email="anonymous@localhost",
            name="Anonymous User",
            picture=None,
            provider="none",
        )



class SessionManager:
    """Manages user sessions and JWT tokens"""

    def __init__(
        self,
        secret_key: str = None,
        private_key_path: str = "keys/private_key.pem",
        public_key_path: str = "keys/public_key.pem",
    ):
        self.secret_key = secret_key  # Keep for backward compatibility
        self.users: Dict[str, User] = {}  # user_id -> User
        self.user_opensearch_clients: Dict[
            str, Any
        ] = {}  # user_id -> OpenSearch client

        # Load RSA keys
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self._load_rsa_keys()

    def _load_rsa_keys(self):
        """Load RSA private and public keys"""
        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )

            with open(self.public_key_path, "rb") as f:
                self.public_key = serialization.load_pem_public_key(f.read())

            # Also get public key in PEM format for JWKS
            self.public_key_pem = open(self.public_key_path, "r").read()

        except FileNotFoundError as e:
            raise Exception(f"RSA key files not found: {e}")
        except Exception as e:
            raise Exception(f"Failed to load RSA keys: {e}")

    async def get_user_info_from_token(
        self, access_token: str
    ) -> Optional[Dict[str, Any]]:
        """Get user info from Google using access token"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    "Failed to get user info",
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return None

        except Exception as e:
            logger.error("Error getting user info", error=str(e))
            return None

    async def create_user_session(
        self, access_token: str, issuer: str
    ) -> Optional[str]:
        """Create user session from OAuth access token"""
        user_info = await self.get_user_info_from_token(access_token)
        if not user_info:
            return None

        # Create or update user
        user_id = user_info["id"]
        user = User(
            user_id=user_id,
            email=user_info["email"],
            name=user_info["name"],
            picture=user_info.get("picture"),
            provider="google",
        )

        # Update last login if user exists
        if user_id in self.users:
            self.users[user_id].last_login = datetime.now()
        else:
            self.users[user_id] = user

        # Create JWT token using the shared method
        return self.create_jwt_token(user)

    def create_jwt_token(self, user: User) -> str:
        """Create JWT token for an existing user"""
        # Use OpenSearch-compatible issuer for OIDC validation
        oidc_issuer = "http://openrag-backend:8000"

        # Create JWT token with OIDC-compliant claims
        now = datetime.utcnow()
        token_payload = {
            # OIDC standard claims
            "iss": oidc_issuer,  # Fixed issuer for OpenSearch OIDC
            "sub": user.user_id,  # Subject (user ID)
            "aud": ["opensearch", "openrag"],  # Audience
            "exp": now + timedelta(days=7),  # Expiration
            "iat": now,  # Issued at
            "auth_time": int(now.timestamp()),  # Authentication time
            # Custom claims
            "user_id": user.user_id,  # Keep for backward compatibility
            "email": user.email,
            "name": user.name,
            "preferred_username": user.email,
            "email_verified": True,
            "roles": ["openrag_user"],  # Backend role for OpenSearch
        }

        token = jwt.encode(token_payload, self.private_key, algorithm="RS256")
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify JWT token and return user info"""
        try:
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],
                audience=["opensearch", "openrag"],
            )
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return self.users.get(user_id)

    def get_user_from_token(self, token: str) -> Optional[User]:
        """Get user from JWT token"""
        payload = self.verify_token(token)
        if payload:
            return self.get_user(payload["user_id"])
        return None

    def get_user_opensearch_client(self, user_id: str, jwt_token: str):
        """Get or create OpenSearch client for user with their JWT"""
        # Get the effective JWT token (handles anonymous JWT creation)
        jwt_token = self.get_effective_jwt_token(user_id, jwt_token)

        # Check if we have a cached client for this user
        if user_id not in self.user_opensearch_clients:
            from config.settings import clients

            self.user_opensearch_clients[user_id] = (
                clients.create_user_opensearch_client(jwt_token)
            )

        return self.user_opensearch_clients[user_id]

    def get_effective_jwt_token(self, user_id: str, jwt_token: str) -> str:
        """Get the effective JWT token, creating anonymous JWT if needed in no-auth mode"""
        from config.settings import is_no_auth_mode

        logger.debug(
            "get_effective_jwt_token",
            user_id=user_id,
            jwt_token_present=(jwt_token is not None),
            no_auth_mode=is_no_auth_mode(),
        )

        # In no-auth mode, create anonymous JWT if needed
        if jwt_token is None and (is_no_auth_mode() or user_id in (None, AnonymousUser().user_id)):
            if not hasattr(self, "_anonymous_jwt"):
                # Create anonymous JWT token for OpenSearch OIDC
                logger.debug("Creating anonymous JWT")
                self._anonymous_jwt = self._create_anonymous_jwt()
                logger.debug(
                    "Anonymous JWT created", jwt_prefix=self._anonymous_jwt[:50]
                )
            jwt_token = self._anonymous_jwt
            logger.debug("Using anonymous JWT")

        return jwt_token

    def _create_anonymous_jwt(self) -> str:
        """Create JWT token for anonymous user in no-auth mode"""
        anonymous_user = AnonymousUser()
        return self.create_jwt_token(anonymous_user)