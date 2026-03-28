import asyncio
import os
import json
from typing import Optional

import requests as req_lib
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from utils.logging_config import get_logger

logger = get_logger(__name__)

_REFRESH_TIMEOUT_SECONDS = 30


class GoogleDriveOAuth:
    """Handles Google Drive OAuth authentication flow"""

    SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]

    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_file: str = "token.json",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.creds: Optional[Credentials] = None

    def _make_timeout_request(self) -> Request:
        """Build a google-auth Request transport with a bounded timeout."""
        session = req_lib.Session()
        session.timeout = _REFRESH_TIMEOUT_SECONDS
        return Request(session=session)

    async def load_credentials(self) -> Optional[Credentials]:
        """Load existing credentials from token file"""
        from utils.encryption import read_encrypted_file

        logger.debug("[GoogleDrive] load_credentials: reading token file %s", self.token_file)
        raw_data, needs_upgrade = await read_encrypted_file(self.token_file)
        if raw_data is None:
            logger.debug("[GoogleDrive] load_credentials: no token file found")
            return None

        try:
            token_data = json.loads(raw_data)
        except Exception:
            logger.debug("[GoogleDrive] load_credentials: corrupted token file, removing")
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
            return None

        logger.debug("[GoogleDrive] load_credentials: token data loaded, creating Credentials object")

        self.creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            id_token=token_data.get("id_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=token_data.get("scopes", self.SCOPES),
        )

        # Set expiry if available (ensure timezone-naive for Google auth compatibility)
        if token_data.get("expiry"):
            from datetime import datetime

            expiry_dt = datetime.fromisoformat(token_data["expiry"])
            self.creds.expiry = expiry_dt.replace(tzinfo=None)
            logger.debug("[GoogleDrive] load_credentials: token expiry=%s", self.creds.expiry)

        if needs_upgrade and self.creds:
            await self.save_credentials()

        if self.creds and self.creds.expired and self.creds.refresh_token:
            logger.debug(
                "[GoogleDrive] load_credentials: token expired, refreshing (timeout=%ss)",
                _REFRESH_TIMEOUT_SECONDS,
            )
            try:
                await asyncio.to_thread(self.creds.refresh, self._make_timeout_request())
                logger.debug("[GoogleDrive] load_credentials: token refresh succeeded")
                await self.save_credentials()
            except Exception as e:
                logger.debug("[GoogleDrive] load_credentials: token refresh failed: %s", e)
                self.creds = None
                if os.path.exists(self.token_file):
                    try:
                        os.remove(self.token_file)
                    except Exception:
                        pass
                raise ValueError(
                    f"Failed to refresh Google Drive credentials. "
                    f"The refresh token may have expired or been revoked. "
                    f"Please re-authenticate: {str(e)}"
                ) from e
        else:
            logger.debug(
                "[GoogleDrive] load_credentials: token valid=%s, expired=%s, has_refresh=%s",
                self.creds.valid if self.creds else None,
                self.creds.expired if self.creds else None,
                bool(self.creds.refresh_token) if self.creds else None,
            )

        return self.creds

    async def save_credentials(self):
        """Save credentials to token file (without client_secret)"""
        if self.creds:
            # Create minimal token data without client_secret
            token_data = {
                "token": self.creds.token,
                "refresh_token": self.creds.refresh_token,
                "id_token": self.creds.id_token,
                "scopes": self.creds.scopes,
            }

            # Add expiry if available
            if self.creds.expiry:
                token_data["expiry"] = self.creds.expiry.isoformat()
                
            from utils.encryption import write_encrypted_file
            await write_encrypted_file(self.token_file, json.dumps(token_data))

    def create_authorization_url(
        self, redirect_uri: str, state: Optional[str] = None
    ) -> str:
        """Create authorization URL for OAuth flow"""
        # Create flow from client credentials directly
        client_config = {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = Flow.from_client_config(
            client_config, scopes=self.SCOPES, redirect_uri=redirect_uri
        )

        kwargs = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",  # Force consent to get refresh token
        }
        if state:
            kwargs["state"] = state

        auth_url, _ = flow.authorization_url(**kwargs)

        # Store flow state for later use
        self._flow_state = flow.state
        self._flow = flow

        return auth_url

    async def handle_authorization_callback(
        self, authorization_code: str, state: str
    ) -> bool:
        """Handle OAuth callback and exchange code for tokens"""
        if not hasattr(self, "_flow") or self._flow_state != state:
            raise ValueError("Invalid OAuth state")

        logger.debug("[GoogleDrive] handle_authorization_callback: exchanging auth code for tokens")
        await asyncio.to_thread(self._flow.fetch_token, code=authorization_code)
        self.creds = self._flow.credentials
        logger.debug("[GoogleDrive] handle_authorization_callback: token exchange complete")

        await self.save_credentials()
        return True

    async def is_authenticated(self) -> bool:
        """Check if we have valid credentials"""
        if not self.creds:
            await self.load_credentials()

        result = bool(self.creds and self.creds.valid)
        logger.debug("[GoogleDrive] is_authenticated: %s", result)
        return result

    def get_service(self):
        """Get authenticated Google Drive service"""
        if not self.creds or not self.creds.valid:
            raise ValueError("Not authenticated")

        logger.debug("[GoogleDrive] get_service: building Drive v3 service")
        return build("drive", "v3", credentials=self.creds)

    async def revoke_credentials(self):
        """Revoke credentials and delete token file"""
        if self.creds:
            logger.debug("[GoogleDrive] revoke_credentials: revoking token")
            await asyncio.to_thread(self.creds.revoke, self._make_timeout_request())

        if os.path.exists(self.token_file):
            os.remove(self.token_file)

        self.creds = None
        logger.debug("[GoogleDrive] revoke_credentials: done")
