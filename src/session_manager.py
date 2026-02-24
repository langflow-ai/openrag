import jwt
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Union
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519, ed448

import os
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
    jwt_token: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_login is None:
            self.last_login = datetime.now()

@dataclass
class AnonymousUser(User):
    """Anonymous user"""

    user_id: str = "anonymous"
    email: str = "anonymous@localhost"
    name: str = "Anonymous User"
    picture: str = None
    provider: str = "none"



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

        self.private_key_path = private_key_path
        self.public_key_path = public_key_path

        # Configure JWT signing (checks env var first, falls back to key files)
        self._configure_jwt_signing()

    def _configure_jwt_signing(self):
        """Configure JWT signing - supports env var or file-based keys"""
        signing_key = os.getenv("JWT_SIGNING_KEY")

        if signing_key:
            if signing_key.lstrip().startswith("-----BEGIN"):
                key = serialization.load_pem_private_key(signing_key.encode(), password=None)

                self.private_key = key
                self.public_key = key.public_key()
                self.public_key_pem = self.public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode()

                if isinstance(key, rsa.RSAPrivateKey):
                    self.algorithm = "RS256"
                elif isinstance(key, ec.EllipticCurvePrivateKey):
                    curve = key.curve
                    if isinstance(curve, ec.SECP256R1):
                        self.algorithm = "ES256"
                    elif isinstance(curve, ec.SECP384R1):
                        self.algorithm = "ES384"
                    elif isinstance(curve, ec.SECP521R1):
                        self.algorithm = "ES512"
                    else:
                        raise ValueError(f"Unsupported EC curve: {curve.name}")
                elif isinstance(key, (ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey)):
                    self.algorithm = "EdDSA"
                else:
                    raise ValueError(f"Unsupported private key type: {type(key)}")

            else:
                # Plain string = symmetric (HS256)
                self.private_key = signing_key
                self.public_key = signing_key  # Same key for verification
                self.public_key_pem = None  # No JWKS for symmetric
                self.algorithm = "HS256"
        else:
            # Fall back to file-based RSA keys
            self._load_rsa_keys()
            self.algorithm = "RS256"
        logger.info(f"Initialized JWT signing with {self.algorithm}")


    def _load_rsa_keys(self):
        """Load RSA private and public keys from files"""
        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )

            with open(self.public_key_path, "rb") as f:
                self.public_key = serialization.load_pem_public_key(f.read())

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
        openrag_fqdn = os.getenv("OPENRAG_FQDN")
        if openrag_fqdn:
            oidc_issuer = f"http://{openrag_fqdn}:8000"

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
            "user_roles": ["openrag_user"],  # compatible with OpenSearch's roles_key
        }

        # Check for token from environment variable first
        token = os.getenv("OPENSEARCH_JWT_TOKEN")
        if not token:
            # If no env token, generate using JWT
            token = jwt.encode(token_payload, self.private_key, algorithm=self.algorithm)
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify JWT token and return user info"""
        try:
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
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

    def get_user_opensearch_client(self, user_or_id: Union[User, str], jwt_token: str = None):
        """Get or create OpenSearch client for user with their JWT"""
        if isinstance(user_or_id, User):
            user_id = user_or_id.user_id
            jwt_token = user_or_id.jwt_token
        else:
            user_id = user_or_id

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
